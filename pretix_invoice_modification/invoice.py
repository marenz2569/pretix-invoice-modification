import logging
from collections import defaultdict
from decimal import Decimal
from io import BytesIO
from typing import Tuple

import bleach
import vat_moss.exchange_rates
from django.contrib.staticfiles import finders
from django.dispatch import receiver
from django.utils.formats import date_format, localize
from django.utils.translation import (
    get_language, gettext, gettext_lazy, pgettext,
)
from reportlab.lib import pagesizes
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, StyleSheet1
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

from pretix.base.decimal import round_decimal
from pretix.base.models import Event, Invoice, Order
from pretix.base.signals import register_invoice_renderers
from pretix.base.templatetags.money import money_filter
from pretix.helpers.reportlab import ThumbnailingImageReader

from pretix.base.invoice import Modern1Renderer

logger = logging.getLogger(__name__)

class ModifiedInvoiceRenderer(Modern1Renderer):
    def _get_story(self, doc):
        has_taxes = any(il.tax_value for il in self.invoice.lines.all()) or self.invoice.reverse_charge

        story = [
            NextPageTemplate('FirstPage'),
            Paragraph(
                (
                    pgettext('invoice', 'Tax Invoice') if str(self.invoice.invoice_from_country) == 'AU'
                    else pgettext('invoice', 'Invoice')
                ) if not self.invoice.is_cancellation else pgettext('invoice', 'Cancellation'),
                self.stylesheet['Heading1']
            ),
            Spacer(1, 5 * mm),
            NextPageTemplate('OtherPages'),
        ]
        story += self._get_intro()

        taxvalue_map = defaultdict(Decimal)
        grossvalue_map = defaultdict(Decimal)

        tstyledata = [
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), self.font_bold),
            ('FONTNAME', (0, -1), (-1, -1), self.font_bold),
            ('LEFTPADDING', (0, 0), (0, -1), 0),
            ('RIGHTPADDING', (-1, 0), (-1, -1), 0),
        ]
        if has_taxes:
            tdata = [(
                pgettext('invoice', 'Description'),
                pgettext('invoice', 'Qty'),
                pgettext('invoice', 'Tax rate'),
                pgettext('invoice', 'Net'),
                pgettext('invoice', 'Gross'),
            )]
        else:
            tdata = [(
                pgettext('invoice', 'Description'),
                pgettext('invoice', 'Qty'),
                pgettext('invoice', 'Amount'),
            )]

        total = Decimal('0.00')
        donation_amount_total = Decimal('0.00')
        for line in self.invoice.lines.all():
            if has_taxes:
                tdata.append((
                    Paragraph(
                        bleach.clean(line.description, tags=['br']).strip().replace('<br>', '<br/>').replace('\n', '<br />\n'),
                        self.stylesheet['Normal']
                    ),
                    "1",
                    localize(line.tax_rate) + " %",
                    money_filter(line.net_value, self.invoice.event.currency),
                    money_filter(line.gross_value, self.invoice.event.currency),
                ))
            else:
                if ("Donation" in line.description) or ("Spende" in line.description):
                    donation_amount_total += line.gross_value
                else:
                    tdata.append((
                        Paragraph(
                            bleach.clean(line.description, tags=['br']).strip().replace('<br>', '<br/>').replace('\n', '<br />\n'),
                            self.stylesheet['Normal']
                        ),
                        "1",
                        money_filter(line.gross_value, self.invoice.event.currency),
                    ))

            taxvalue_map[line.tax_rate, line.tax_name] += line.tax_value
            grossvalue_map[line.tax_rate, line.tax_name] += line.gross_value
            total += line.gross_value

        if not donation_amount_total.is_zero():
            tdata.append((
                Paragraph(
                    "Spende",
                    self.stylesheet['Normal']
                ),
                "1",
                money_filter(donation_amount_total, self.invoice.event.currency),
            ))

        if has_taxes:
            tdata.append([
                pgettext('invoice', 'Invoice total'), '', '', '', money_filter(total, self.invoice.event.currency)
            ])
            colwidths = [a * doc.width for a in (.50, .05, .15, .15, .15)]
        else:
            tdata.append([
                pgettext('invoice', 'Invoice total'), '', money_filter(total, self.invoice.event.currency)
            ])
            colwidths = [a * doc.width for a in (.65, .05, .30)]

        if self.invoice.event.settings.invoice_show_payments and not self.invoice.is_cancellation and \
                self.invoice.order.status == Order.STATUS_PENDING:
            pending_sum = self.invoice.order.pending_sum
            if pending_sum != total:
                tdata.append([pgettext('invoice', 'Received payments')] + (['', '', ''] if has_taxes else ['']) + [
                    money_filter(pending_sum - total, self.invoice.event.currency)
                ])
                tdata.append([pgettext('invoice', 'Outstanding payments')] + (['', '', ''] if has_taxes else ['']) + [
                    money_filter(pending_sum, self.invoice.event.currency)
                ])
                tstyledata += [
                    ('FONTNAME', (0, len(tdata) - 3), (-1, len(tdata) - 3), self.font_bold),
                ]

        table = Table(tdata, colWidths=colwidths, repeatRows=1)
        table.setStyle(TableStyle(tstyledata))
        story.append(table)

        story.append(Spacer(1, 10 * mm))

        if self.invoice.payment_provider_text:
            story.append(Paragraph(
                self.invoice.payment_provider_text,
                self.stylesheet['Normal']
            ))

        if self.invoice.payment_provider_text and self.invoice.additional_text:
            story.append(Spacer(1, 3 * mm))

        if self.invoice.additional_text:
            story.append(Paragraph(
                self.invoice.additional_text,
                self.stylesheet['Normal']
            ))
            story.append(Spacer(1, 5 * mm))

        tstyledata = [
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (0, -1), 0),
            ('RIGHTPADDING', (-1, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('FONTNAME', (0, 0), (-1, -1), self.font_regular),
        ]
        thead = [
            pgettext('invoice', 'Tax rate'),
            pgettext('invoice', 'Net value'),
            pgettext('invoice', 'Gross value'),
            pgettext('invoice', 'Tax'),
            ''
        ]
        tdata = [thead]

        for idx, gross in grossvalue_map.items():
            rate, name = idx
            if rate == 0:
                continue
            tax = taxvalue_map[idx]
            tdata.append([
                localize(rate) + " % " + name,
                money_filter(gross - tax, self.invoice.event.currency),
                money_filter(gross, self.invoice.event.currency),
                money_filter(tax, self.invoice.event.currency),
                ''
            ])

        def fmt(val):
            try:
                return vat_moss.exchange_rates.format(val, self.invoice.foreign_currency_display)
            except ValueError:
                return localize(val) + ' ' + self.invoice.foreign_currency_display

        if len(tdata) > 1 and has_taxes:
            colwidths = [a * doc.width for a in (.25, .15, .15, .15, .3)]
            table = Table(tdata, colWidths=colwidths, repeatRows=2, hAlign=TA_LEFT)
            table.setStyle(TableStyle(tstyledata))
            story.append(Spacer(5 * mm, 5 * mm))
            story.append(KeepTogether([
                Paragraph(pgettext('invoice', 'Included taxes'), self.stylesheet['FineprintHeading']),
                table
            ]))

            if self.invoice.foreign_currency_display and self.invoice.foreign_currency_rate:
                tdata = [thead]

                for idx, gross in grossvalue_map.items():
                    rate, name = idx
                    if rate == 0:
                        continue
                    tax = taxvalue_map[idx]
                    gross = round_decimal(gross * self.invoice.foreign_currency_rate)
                    tax = round_decimal(tax * self.invoice.foreign_currency_rate)
                    net = gross - tax

                    tdata.append([
                        localize(rate) + " % " + name,
                        fmt(net), fmt(gross), fmt(tax), ''
                    ])

                table = Table(tdata, colWidths=colwidths, repeatRows=2, hAlign=TA_LEFT)
                table.setStyle(TableStyle(tstyledata))

                story.append(KeepTogether([
                    Spacer(1, height=2 * mm),
                    Paragraph(
                        pgettext(
                            'invoice', 'Using the conversion rate of 1:{rate} as published by the European Central Bank on '
                                       '{date}, this corresponds to:'
                        ).format(rate=localize(self.invoice.foreign_currency_rate),
                                 date=date_format(self.invoice.foreign_currency_rate_date, "SHORT_DATE_FORMAT")),
                        self.stylesheet['Fineprint']
                    ),
                    Spacer(1, height=3 * mm),
                    table
                ]))
        elif self.invoice.foreign_currency_display and self.invoice.foreign_currency_rate:
            foreign_total = round_decimal(total * self.invoice.foreign_currency_rate)
            story.append(Spacer(1, 5 * mm))
            story.append(Paragraph(
                pgettext(
                    'invoice', 'Using the conversion rate of 1:{rate} as published by the European Central Bank on '
                               '{date}, the invoice total corresponds to {total}.'
                ).format(rate=localize(self.invoice.foreign_currency_rate),
                         date=date_format(self.invoice.foreign_currency_rate_date, "SHORT_DATE_FORMAT"),
                         total=fmt(foreign_total)),
                self.stylesheet['Fineprint']
            ))

        return story

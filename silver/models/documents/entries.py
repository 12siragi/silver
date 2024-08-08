# Copyright (c) 2016 Presslabs SRL
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import, unicode_literals

import datetime as dt
from dataclasses import dataclass

from decimal import Decimal
from enum import Enum

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from silver.utils.decorators import require_transaction_currency_and_xe_rate
from silver.utils.models import AutoCleanModelMixin


class DocumentEntry(AutoCleanModelMixin, models.Model):
    description = models.TextField()
    unit = models.CharField(max_length=1024, blank=True, null=True)
    quantity = models.DecimalField(max_digits=19, decimal_places=4,
                                   validators=[MinValueValidator(0.0)])
    unit_price = models.DecimalField(max_digits=19, decimal_places=4)
    product_code = models.ForeignKey('ProductCode', null=True, blank=True,
                                     related_name='invoices', on_delete=models.PROTECT)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    prorated = models.BooleanField(default=False)
    invoice = models.ForeignKey('BillingDocumentBase', related_name='invoice_entries',
                                blank=True, null=True, on_delete=models.CASCADE)
    proforma = models.ForeignKey('BillingDocumentBase', related_name='proforma_entries',
                                 blank=True, null=True, on_delete=models.CASCADE)

    class Meta:
        verbose_name = 'Entry'
        verbose_name_plural = 'Entries'

    def full_clean(self, *args, **kwargs):
        quantized_unit_price = Decimal(self.unit_price).quantize(Decimal(f".{'0'*self.unit_price_decimals}"))

        if self.unit_price == quantized_unit_price:
            self.unit_price = quantized_unit_price

        quantized_quantity = Decimal(self.quantity).quantize(Decimal('0.0000'))

        if self.quantity == quantized_quantity:
            self.quantity = quantized_quantity

        super().full_clean(*args, **kwargs)

    @property
    def document(self):
        return self.invoice or self.proforma

    @property
    def total(self):
        return self.total_before_tax + self.tax_value

    @property
    def total_before_tax(self):
        result = Decimal(self.quantity * self.unit_price)
        return result.quantize(Decimal('0.00'))

    @property
    def tax_value(self):
        if self.invoice:
            sales_tax_percent = self.invoice.sales_tax_percent
        elif self.proforma:
            sales_tax_percent = self.proforma.sales_tax_percent
        else:
            sales_tax_percent = None

        if not sales_tax_percent:
            return Decimal('0.00')

        result = self.total_before_tax * sales_tax_percent / 100
        return result.quantize(Decimal('0.00'))

    @property
    @require_transaction_currency_and_xe_rate
    def total_in_transaction_currency(self):
        return (self.total_before_tax_in_transaction_currency +
                self.tax_value_in_transaction_currency)

    @property
    def unit_price_decimals(self) -> int:
        return int(getattr(settings, 'SILVER_DEFAULT_UNIT_PRICE_DECIMALS', 4))

    @property
    def unit_price_in_transaction_currency(self):
        result = Decimal(self.unit_price) * self.transaction_xe_rate
        return result.quantize(Decimal(f".{'0'*self.unit_price_decimals}"))

    @property
    @require_transaction_currency_and_xe_rate
    def total_before_tax_in_transaction_currency(self):
        result = Decimal(self.quantity) * self.unit_price_in_transaction_currency
        return result.quantize(Decimal('0.00'))

    @property
    @require_transaction_currency_and_xe_rate
    def tax_value_in_transaction_currency(self):
        if self.invoice:
            sales_tax_percent = self.invoice.sales_tax_percent
        elif self.proforma:
            sales_tax_percent = self.proforma.sales_tax_percent
        else:
            sales_tax_percent = None

        if not sales_tax_percent:
            return Decimal('0.00')

        result = self.total_before_tax_in_transaction_currency * sales_tax_percent / 100
        return result.quantize(Decimal('0.00'))

    @property
    def transaction_currency(self):
        return self.document.transaction_currency

    @property
    def currency(self):
        return self.document.currency

    @property
    def transaction_xe_rate(self):
        if self.document.currency == self.document.transaction_currency:
            return Decimal('1.00')

        return self.document.transaction_xe_rate

    def clone(self):
        return DocumentEntry(
            description=self.description,
            unit=self.unit,
            quantity=self.quantity,
            unit_price=self.unit_price,
            product_code=self.product_code,
            start_date=self.start_date,
            end_date=self.end_date,
            prorated=self.prorated
        )

    def __str__(self):
        s = u'{descr} - {unit} - {unit_price} - {quantity} - {product_code}'
        return s.format(
            descr=self.description,
            unit=self.unit,
            unit_price=self.unit_price,
            quantity=self.quantity,
            product_code=self.product_code
        )


class OriginType(str, Enum):
    Plan = "plan"
    MeteredFeature = "metered_feature"


@dataclass(frozen=True, eq=True)
class EntryInfo:
    start_date: dt.date
    end_date: dt.date
    origin_type: OriginType
    subscription: "silver.models.Subscription"
    product_code: "silver.models.ProductCode"
    amount: Decimal

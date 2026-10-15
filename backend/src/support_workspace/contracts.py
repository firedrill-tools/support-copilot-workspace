"""Local workspace integrity; preserve additional fictional business context."""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Any, Literal


class Record(BaseModel):
    model_config = ConfigDict(extra="allow")


class Order(Record):
    id: str = Field(min_length=1)
    customer_email: str = Field(min_length=3)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    status: str
    total_cents: int = Field(strict=True,ge=0)
    paid_cents: int = Field(strict=True,ge=0)
    refunded_cents: int = Field(strict=True,ge=0)

    @model_validator(mode="after")
    def balance(self):
        if not self.refunded_cents <= self.paid_cents <= self.total_cents:
            raise ValueError("invalid captured/refunded balance")
        return self


class Case(Record):
    id: str = Field(min_length=1)
    order_id: str
    email: str = Field(min_length=3)
    customer: str
    subject: str
    message: str
    status: Literal["open","refunded","rejected"]
    revision: int = Field(strict=True,ge=0)
    proposal: dict[str,Any] | None
    resolution: dict[str,Any] | None


class Refund(Record):
    id: str = Field(min_length=1)
    case_id: str
    order_id: str
    amount_cents: int = Field(strict=True,gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class WorkspaceData(Record):
    cases: list[Case]
    orders: list[Order]
    refunds: list[Refund]

    @model_validator(mode="after")
    def relationships(self):
        orders={item.id:item for item in self.orders}
        cases={item.id:item for item in self.cases}
        refunds={item.id:item for item in self.refunds}
        if len(orders)!=len(self.orders) or len(cases)!=len(self.cases) or len(refunds)!=len(self.refunds):
            raise ValueError("duplicate workspace identity")
        if any(case.order_id not in orders for case in self.cases):
            raise ValueError("unknown case order")
        for refund in self.refunds:
            if refund.order_id not in orders or refund.case_id not in cases:
                raise ValueError("unknown refund order/case")
            if refund.currency != orders[refund.order_id].currency:
                raise ValueError("refund currency differs from order")
        for order in self.orders:
            if sum(item.amount_cents for item in self.refunds if item.order_id==order.id)>order.refunded_cents:
                raise ValueError("refund records exceed ledger amount")
        for case in self.cases:
            if case.status=="refunded":
                resolution=case.resolution or {}
                refund=refunds.get(resolution.get("id"))
                if refund is None or refund.case_id!=case.id or refund.order_id!=case.order_id or refund.model_dump()!=resolution:
                    raise ValueError("case resolution does not match its committed refund")
        return self

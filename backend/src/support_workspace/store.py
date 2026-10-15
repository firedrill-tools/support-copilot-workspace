"""Committed workspace state shared by HTTP UI and agent tools."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from .contracts import WorkspaceData


class Conflict(Exception):
    pass


class Workspace:
    def __init__(self, path: Path):
        self.path = path
        self.lock = Lock()
        if not path.exists():
            raise FileNotFoundError(f"workspace missing: {path}")
        self._read()

    def _read(self):
        data = json.loads(self.path.read_text())
        WorkspaceData.model_validate(data)
        return data

    def _write(self, data):
        WorkspaceData.model_validate(data)
        temporary = None
        try:
            with NamedTemporaryFile(mode="w",encoding="utf8",dir=self.path.parent,prefix=f".{self.path.name}.",suffix=".tmp",delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data,stream,indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary,self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def cases(self):
        return self._read()["cases"]

    def case(self, case_id: str):
        data = self._read()
        case = next((c for c in data["cases"] if c["id"] == case_id), None)
        if not case:
            raise KeyError("unknown case")
        order = next(o for o in data["orders"] if o["id"] == case["order_id"])
        return {"case": case, "order": order,
                "refunds": [r for r in data["refunds"] if r["case_id"] == case_id]}

    def propose(self, case_id: str, amount_cents: int, reason: str):
        if type(amount_cents) is not int or amount_cents <= 0:
            raise ValueError("proposed amount must be a positive integer")
        if not isinstance(reason,str) or not 5 <= len(reason.strip()) <= 1000:
            raise ValueError("proposal reason must contain 5–1000 nonblank characters")
        with self.lock:
            data = self._read()
            case = next((c for c in data["cases"] if c["id"] == case_id), None)
            if not case:
                raise KeyError("unknown case")
            if case["status"] != "open":
                raise Conflict("case is closed")
            order = next(o for o in data["orders"] if o["id"] == case["order_id"])
            if amount_cents <= 0 or amount_cents > order["paid_cents"] - order["refunded_cents"]:
                raise ValueError("proposed amount exceeds captured balance")
            proposal = {"amount_cents": amount_cents, "currency": order["currency"], "reason": reason,
                        "binding": {"order_id":order["id"], "customer_email":order["customer_email"].casefold(),"currency":order["currency"]}}
            if case["proposal"] == proposal:
                return case
            case["proposal"] = proposal
            case["revision"] += 1
            self._write(data)
            return case

    def decide(self, case_id: str, revision: int, decision: str):
        if type(revision) is not int or revision < 0:
            raise ValueError("revision must be a nonnegative integer")
        if decision not in {"approve","reject"}:
            raise ValueError("decision must be approve or reject")
        with self.lock:
            data = self._read()
            case = next((c for c in data["cases"] if c["id"] == case_id), None)
            if not case:
                raise KeyError("unknown case")
            if case["revision"] != revision:
                raise Conflict("case changed; reload before deciding")
            if case["status"] != "open" or not case["proposal"]:
                raise Conflict("no pending proposal")
            order = next(o for o in data["orders"] if o["id"] == case["order_id"])
            if decision == "approve":
                amount = case["proposal"]["amount_cents"]
                binding = {"order_id":order["id"],"customer_email":order["customer_email"].casefold(),"currency":order["currency"]}
                if case["proposal"].get("binding") != binding or case["proposal"].get("currency") != order["currency"]:
                    raise Conflict("proposal order, customer or currency changed; create a fresh proposal")
                if type(amount) is not int or amount <= 0:
                    raise Conflict("proposal amount is invalid")
                if order["status"] != "delivered" or case["email"].casefold() != order["customer_email"].casefold():
                    raise Conflict("order does not qualify for a refund")
                if amount > order["paid_cents"] - order["refunded_cents"]:
                    raise Conflict("captured balance changed")
                existing = {refund["id"] for refund in data["refunds"]}
                sequence = max((int(identifier.removeprefix("refund-")) for identifier in existing if identifier.startswith("refund-") and identifier.removeprefix("refund-").isdigit()),default=0)+1
                refund = {"id": f"refund-{sequence:03d}", "case_id": case_id,
                          "order_id": order["id"], "amount_cents": amount, "currency": order["currency"]}
                data["refunds"].append(refund)
                order["refunded_cents"] += amount
                case["resolution"] = refund
                case["status"] = "refunded"
            elif decision == "reject":
                case["status"] = "rejected"
                case["resolution"] = {"reason": "Proposal rejected by support operator"}
            else:
                raise ValueError("decision must be approve or reject")
            case["revision"] += 1
            self._write(data)
            return {"case": case, "order": order}

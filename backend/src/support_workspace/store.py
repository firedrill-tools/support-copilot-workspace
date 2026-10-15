"""Committed workspace state shared by HTTP UI and agent tools."""
import json
import os
from pathlib import Path
from threading import Lock


class Conflict(Exception):
    pass


class Workspace:
    def __init__(self, path: Path):
        self.path = path
        self.lock = Lock()
        if not path.exists():
            raise FileNotFoundError(f"workspace missing: {path}")

    def _read(self):
        return json.loads(self.path.read_text())

    def _write(self, data):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, self.path)

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
            case["proposal"] = {"amount_cents": amount_cents, "currency": order["currency"], "reason": reason}
            case["revision"] += 1
            self._write(data)
            return case

    def decide(self, case_id: str, revision: int, decision: str):
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
                if order["status"] != "delivered" or case["email"].casefold() != order["customer_email"].casefold():
                    raise Conflict("order does not qualify for a refund")
                if amount > order["paid_cents"] - order["refunded_cents"]:
                    raise Conflict("captured balance changed")
                refund = {"id": f"refund-{len(data['refunds']) + 1:03d}", "case_id": case_id,
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

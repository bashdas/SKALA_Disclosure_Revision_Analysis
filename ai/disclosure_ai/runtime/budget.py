import json
import time

from disclosure_ai.domain.errors import LimitReached


class RunBudget:
    def remaining(self, report: bool = False) -> float:
        reserve = 0 if report else 30
        return 120 - reserve - (time.time() - self.ledger.row(self.task_id)["started"])

    async def reserve(self, tokens: int, report: bool = False, role: str = "") -> None:
        async with self.ledger.lock:
            row = self.ledger.row(self.task_id)
            role_counts = json.loads(row["tools"])
            if role.startswith("perspective:") and role_counts.get("model:" + role, 0) >= 3:
                raise LimitReached("관점별 모델 호출 한도에 도달했습니다.")
            ceiling = 60000 if report else 48000
            turns = 8 if report else 7
            if (
                self.remaining(report) <= 0
                or row["turns"] >= turns
                or row["tokens"] + tokens > ceiling
            ):
                raise LimitReached("실행 시간, 모델 턴 또는 토큰 한도에 도달했습니다.")
            self.ledger.db.execute(
                "UPDATE runs SET turns=turns+1,tokens=tokens+? WHERE id=?", (tokens, self.task_id)
            )
            if role:
                role_counts["model:" + role] = role_counts.get("model:" + role, 0) + 1
                self.ledger.db.execute(
                    "UPDATE runs SET tools=? WHERE id=?", (json.dumps(role_counts), self.task_id)
                )
            self.ledger.db.commit()

import pandas as pd
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

# ---- Pricing (USD per 1M tokens) ----
PRICES_USD_PER_MTOK: Dict[str, Dict[str, float]] = {
    # GPT-5 family
    "gpt-5":        {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5-mini":   {"input": 0.25, "cached_input": 0.025, "output": 2.00},
    "gpt-5-nano":   {"input": 0.05, "cached_input": 0.005, "output": 0.40},
    "gpt-5-chat-latest": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    # GPT-4o family
    "gpt-4o":       {"input": 5.00,  "cached_input": 2.50,  "output": 20.00},
    "gpt-4o-mini":  {"input": 0.60,  "cached_input": 0.30,  "output": 2.40},
    # Fallback
    "default":      {"input": 5.00,  "cached_input": 2.50,  "output": 15.00},
}

@dataclass
class UsageRecord:
    ts: str
    endpoint: str
    model: str
    prompt_tokens: int
    cached_prompt_tokens: int
    billable_prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    est_cost_usd: float

def _as_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (ValueError, TypeError):
        return default

def _extract_usage_from_response(response: Any) -> Optional[Dict[str, Any]]:
    if response is None:
        return None
    if isinstance(response, dict) and "prompt_tokens" in response:
        return response
    usage = getattr(response, "usage", None)
    if usage:
        try:
            return usage.model_dump()
        except AttributeError:
            return asdict(usage)
    return None

class ApiUsageTracker:
    def __init__(self, price_table: Optional[Dict[str, Dict[str, float]]] = None):
        self.price_table = price_table or PRICES_USD_PER_MTOK
        self._rows: List[UsageRecord] = []

    def log_call(self, *, endpoint: str, model: str, response: Any = None, usage: Any = None, ts: Optional[datetime] = None):
        usage_dict = usage or _extract_usage_from_response(response)
        if not usage_dict:
            return

        prompt_tokens = _as_int(usage_dict.get("prompt_tokens", 0))
        completion_tokens = _as_int(usage_dict.get("completion_tokens", 0))
        total_tokens = _as_int(usage_dict.get("total_tokens", prompt_tokens + completion_tokens))
        
        ptd = usage_dict.get("prompt_tokens_details", {}) or {}
        cached_prompt_tokens = _as_int(ptd.get("cached_tokens", 0))
        billable_prompt_tokens = max(prompt_tokens - cached_prompt_tokens, 0)

        est_cost = self._estimate_cost_usd(
            model=model,
            billable_prompt_tokens=billable_prompt_tokens,
            cached_prompt_tokens=cached_prompt_tokens,
            completion_tokens=completion_tokens,
        )

        rec = UsageRecord(
            ts=(ts or datetime.utcnow()).isoformat(), endpoint=endpoint, model=model,
            prompt_tokens=prompt_tokens, cached_prompt_tokens=cached_prompt_tokens,
            billable_prompt_tokens=billable_prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=total_tokens, est_cost_usd=est_cost,
        )
        self._rows.append(rec)

    def summary(self) -> pd.DataFrame:
        if not self._rows:
            return pd.DataFrame(columns=["Model", "Endpoint(s)", "Calls", "Prompt Tokens", "Completion Tokens", "Total Tokens", "Estimated Cost (USD)"])

        df = pd.DataFrame([asdict(r) for r in self._rows])
        grouped = df.groupby("model").agg(
            Calls=("model", "count"),
            Prompt_Tokens=("prompt_tokens", "sum"),
            Completion_Tokens=("completion_tokens", "sum"),
            Total_Tokens=("total_tokens", "sum"),
            Estimated_Cost_USD=("est_cost_usd", "sum"),
        ).reset_index()

        summary = grouped.rename(columns={
            "model": "Model", "Calls": "Calls", "Prompt_Tokens": "Prompt Tokens",
            "Completion_Tokens": "Completion Tokens", "Total_Tokens": "Total Tokens",
            "Estimated_Cost_USD": "Estimated Cost (USD)",
        })

        totals = {
            "Model": "TOTAL", "Calls": summary["Calls"].sum(),
            "Prompt Tokens": summary["Prompt Tokens"].sum(),
            "Completion Tokens": summary["Completion Tokens"].sum(),
            "Total Tokens": summary["Total Tokens"].sum(),
            "Estimated Cost (USD)": summary["Estimated Cost (USD)"].sum(),
        }
        summary = pd.concat([summary, pd.DataFrame([totals])], ignore_index=True)
        summary["Estimated Cost (USD)"] = summary["Estimated Cost (USD)"].map('{:,.6f}'.format)
        return summary

    def _get_prices(self, model: str) -> Dict[str, float]:
        if model not in self.price_table:
            logging.warning(f"Model '{model}' not in price table. Using 'default' prices.")
            return self.price_table["default"]
        return self.price_table[model]

    def _estimate_cost_usd(self, *, model: str, billable_prompt_tokens: int, cached_prompt_tokens: int, completion_tokens: int) -> float:
        prices = self._get_prices(model)
        i_cost = (billable_prompt_tokens / 1_000_000) * prices["input"]
        ci_cost = (cached_prompt_tokens / 1_000_000) * prices.get("cached_input", prices["input"])
        o_cost = (completion_tokens / 1_000_000) * prices["output"]
        return round(i_cost + ci_cost + o_cost, 8)

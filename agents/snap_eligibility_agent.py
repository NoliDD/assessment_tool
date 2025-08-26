from .base_agent import BaseAgent
import pandas as pd
import logging
import json
import re
from typing import Optional, Tuple

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("SNAP Eligibility")
        self.issue_column = "SNAPEligibilityIssues?"
        self.vertical = None  # set by app (e.g., "CnG")
        # Preferred explicit column name if present
        self.snap_eligible_col = "SNAP_ELIGIBLE"

    # ---------------------------- helpers ----------------------------
    @staticmethod
    def _find_snap_col(df: pd.DataFrame, preferred: Optional[str] = None) -> Optional[str]:
        """Heuristically locate the SNAP eligibility column."""
        cols = list(df.columns)
        # 1) Exact/CI match for preferred name
        if preferred:
            for c in cols:
                if c.strip().lower() == preferred.lower():
                    return c
        # 2) Regex on tokens (handles spaces/underscores): SNAP.*ELIGIBLE
        pat = re.compile(r"\bsnap\b.*\beligib", re.IGNORECASE)
        for c in cols:
            if pat.search(c.replace("_", " ")):
                return c
        # 3) Common variants
        candidates = {
            "SNAP_ELIGIBLE", "SNAP ELIGIBLE", "IS_SNAP_ELIGIBLE", "ELIGIBLE_FOR_SNAP",
            "SNAP_FLAG", "SNAP", "ELIGIBLE SNAP"
        }
        up = {c.upper(): c for c in cols}
        for k in candidates:
            if k in up:
                return up[k]
        return None

    @staticmethod
    def _to_bool_series(s: pd.Series) -> pd.Series:
        """Coerce a mixed-type SNAP flag column into booleans."""
        true_set = {"true", "t", "yes", "y", "1"}
        false_set = {"false", "f", "no", "n", "0"}
        def coerce(v):
            if pd.isna(v):
                return False
            if isinstance(v, (bool,)):
                return bool(v)
            if isinstance(v, (int, float)):
                return bool(int(v))
            sv = str(v).strip().lower()
            if sv in true_set:
                return True
            if sv in false_set:
                return False
            # unknown token -> treat as False
            return False
        return s.map(coerce)

    @staticmethod
    def _ensure_taxonomy_path(df: pd.DataFrame) -> Tuple[pd.DataFrame, bool]:
        """
        Ensure df has 'Taxonomy Path'. If missing, try to build from L1..L4 columns.
        Returns (df, created_flag).
        """
        if "Taxonomy Path" in df.columns:
            return df, False
        cat_cols = [c for c in [f"L{i}_CATEGORY" for i in range(1, 5)] if c in df.columns]
        if not cat_cols:
            # can't build; leave as missing
            return df, False
        df = df.copy()
        df["Taxonomy Path"] = (
            df[cat_cols]
            .astype(str)
            .apply(lambda row: " > ".join([v for v in row if v and str(v).strip().lower() not in {"", "nan", "none", "null"}]), axis=1)
        )
        return df, True

    @staticmethod
    def _alcohol_mask(df: pd.DataFrame) -> pd.Series:
        """Detect alcohol rows via explicit flag if present, else via path keywords."""
        # 1) explicit boolean column
        alcohol_flag = None
        for cand in ["IS_ALCOHOL", "ALCOHOL", "ALCOHOL_FLAG", "IS_ALCOHOLIC"]:
            for c in df.columns:
                if c.strip().upper() == cand:
                    alcohol_flag = c; break
            if alcohol_flag: break
        if alcohol_flag is not None:
            return Agent._to_bool_series(df[alcohol_flag])

        # 2) fallback: keywords in taxonomy path / category columns
        text = None
        if "Taxonomy Path" in df.columns:
            text = df["Taxonomy Path"].astype(str)
        else:
            # try to compose a temporary text from L1/L2
            parts = []
            for c in ["L1_CATEGORY", "L2_CATEGORY", "L3_CATEGORY", "L4_CATEGORY"]:
                if c in df.columns:
                    parts.append(df[c].astype(str))
            if parts:
                text = (" > ".join(parts)).split(" > ")  # not ideal but unlikely to be used if Path missing
        if text is None:
            # if absolutely nothing to go on, return False for all
            return pd.Series([False] * len(df), index=df.index)

        pattern = re.compile(
            r"\b(alcohol|beer|wine|liquor|spirit|vodka|whisk(e?)y|tequila|rum|cider|sake|mezcal)\b",
            re.IGNORECASE,
        )
        return text.str.contains(pattern, na=False)

    # ----------------------------- assess ----------------------------
    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Flags:
          1) Alcohol items incorrectly marked as SNAP-eligible.
          2) Items likely SNAP-eligible not marked as such (heuristic keyword list).
        Only runs for CnG vertical; otherwise writes 'N/A' to issue column.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        if self.issue_column not in df.columns:
            df[self.issue_column] = ""

        # Only CnG
        if self.vertical and self.vertical.strip().lower() != "cng":
            logging.info("Skipping SNAP check: not a CnG vertical.")
            df[self.issue_column] = "N/A: Not a CnG vertical."
            return df

        # Locate SNAP column
        snap_col = self._find_snap_col(df, self.snap_eligible_col)
        # Ensure/Build taxonomy path (if possible)
        df, _ = self._ensure_taxonomy_path(df)

        if snap_col is None:
            df[self.issue_column] = "❌ Missing required column: SNAP eligibility flag."
            return df

        # Coerce to bool
        snap_bool = self._to_bool_series(df[snap_col])

        # Alcohol detection
        alcohol_mask = self._alcohol_mask(df)

        # 1) Alcohol items incorrectly marked SNAP-eligible
        invalid_snap_mask = alcohol_mask & snap_bool
        df.loc[invalid_snap_mask, self.issue_column] = (
            df[self.issue_column].astype(str) + "❌ Alcohol item incorrectly marked as SNAP eligible. "
        )

        # 2) Items likely SNAP-eligible but not marked (heuristic)
        # You can refine this keyword list based on your taxonomy
        snap_keywords = [
            "fruit", "vegetable", "meat", "poultry", "fish", "dairy",
            "bread", "cereal", "snack", "non-alcoholic", "beverage",
            "seed", "plant", "frozen", "produce", "grocery"
        ]
        if "Taxonomy Path" in df.columns:
            snap_eligible_mask = df["Taxonomy Path"].astype(str).str.contains("|".join(snap_keywords), case=False, na=False)
        else:
            # if no path, we can't infer; mark none
            snap_eligible_mask = pd.Series([False] * len(df), index=df.index)

        unmarked_snap_mask = snap_eligible_mask & (~snap_bool) & (~alcohol_mask)
        df.loc[unmarked_snap_mask, self.issue_column] = (
            df[self.issue_column].astype(str) + "❌ Item is SNAP eligible but not marked. "
        )

        return df

    # ---------------------------- summary ----------------------------
    def get_summary(self, df: pd.DataFrame) -> dict:
        """Summary metrics for SNAP eligibility issues."""
        snap_col = self._find_snap_col(df, self.snap_eligible_col)
        if snap_col is None or self.issue_column not in df.columns:
            logging.warning("SNAP Eligibility summary failed: Missing required columns.")
            return {
                "name": self.attribute_name,
                "issue_count": "N/A",
                "issue_percent": 0,
                "snap_eligible_count": 0,
                "alcohol_in_snap_count": 0,
                "unmarked_snap_eligible_items": 0,
            }

        total = len(df)
        snap_bool = self._to_bool_series(df[snap_col])
        snap_eligible_count = int(snap_bool.sum())

        alcohol_in_snap_count = int(
            df[self.issue_column].astype(str).str.contains("Alcohol item incorrectly marked as SNAP eligible", na=False).sum()
        )
        unmarked_snap_eligible_items = int(
            df[self.issue_column].astype(str).str.contains("Item is SNAP eligible but not marked", na=False).sum()
        )
        issue_count = alcohol_in_snap_count + unmarked_snap_eligible_items
        issue_percent = (issue_count / total) * 100 if total else 0.0

        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "snap_eligible_count": snap_eligible_count,
            "alcohol_in_snap_count": alcohol_in_snap_count,
            "unmarked_snap_eligible_items": unmarked_snap_eligible_items,
        }
        logging.info(f"SNAP Eligibility Agent Summary: {json.dumps(summary, indent=2)}")
        return summary

from .base_agent import BaseAgent
import pandas as pd

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Weighted Item")

    def assess(self, df):
        print(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''
        if 'IS_WEIGHTED_ITEM' in df.columns and 'AVERAGE_WEIGHT' in df.columns:
            weighted_mask = df['IS_WEIGHTED_ITEM'] == True
            missing_weight_mask = weighted_mask & df['AVERAGE_WEIGHT'].isnull()
            df.loc[missing_weight_mask, self.issue_column] += '❌ Weighted item is missing AVERAGE_WEIGHT. '
            valid_uom = ['LB', 'KG']
            if 'AVERAGE_WEIGHT_UOM' in df.columns:
                invalid_uom_mask = weighted_mask & ~df['AVERAGE_WEIGHT_UOM'].str.upper().isin(valid_uom)
                df.loc[invalid_uom_mask, self.issue_column] += '❌ Average weight UOM is not LB or KG. '
        return df
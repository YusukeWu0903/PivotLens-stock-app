"""
src/config_manager.py
策略設定管理模組

將策略參數集中管理，未來可擴展為從 JSON/YAML 讀取。
"""

# ==========================================
# 策略設定字典 (未來可移至外部配置檔)
# ==========================================
STRATEGY_CONFIG = {
    "短多 (日K 5MA + 20MA)": {
        "timeframe": "D",
        "short_ma": 5,
        "long_ma": 20,
        "n_days": 5,
        "desc": "適合短線動能追蹤：抓取日線 5MA 近 5 日黃金交叉 20MA 且股價回測月線附近之標的。",
    },
    "中多 (日K 20MA + 60MA)": {
        "timeframe": "D",
        "short_ma": 20,
        "long_ma": 60,
        "n_days": 10,
        "desc": "適合波段佈局：抓取日線 20MA 近 10 日黃金交叉 60MA（季線）且月線斜率向上之標的。",
    },
    "長多 (周K 13MA + 52MA)": {
        "timeframe": "W",
        "short_ma": 13,
        "long_ma": 52,
        "n_days": 20,
        "desc": "適合大趨勢保護：抓取周線 13MA 近 20 周黃金交叉 52MA（一年）之長線趨勢發動股。",
    },
}


def get_strategy_config(strategy_name: str | None = None) -> dict:
    """
    取得策略設定。
    
    Args:
        strategy_name: 策略名稱，若為 None 則回傳所有策略設定
    
    Returns:
        dict: 策略設定字典
    """
    if strategy_name is None:
        return STRATEGY_CONFIG
    return STRATEGY_CONFIG.get(strategy_name, {})


def get_strategy_names() -> list[str]:
    """取得所有策略名稱列表"""
    return list(STRATEGY_CONFIG.keys())


def validate_strategy_params(params: dict) -> bool:
    """
    驗證策略參數是否完整
    
    Args:
        params: 策略參數字典
    
    Returns:
        bool: 參數是否有效
    """
    required_keys = {"timeframe", "short_ma", "long_ma", "n_days"}
    return all(key in params for key in required_keys)
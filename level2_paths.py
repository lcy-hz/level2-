"""Shared local source configuration; loaded once per process, restart to apply."""
import json
from pathlib import Path

CONFIG = Path(__file__).with_name('level2_paths.json')

def load_paths(config=CONFIG):
    values=json.loads(Path(config).read_text())
    required={'level2','stock_minute','stk_factor_pro','daily','stock_basic'}
    if not required.issubset(values) or set(values)-required-{'stk_factor_pro_by_code'}:raise ValueError('路径配置字段必须为：'+', '.join(sorted(required)))
    result={}
    for key,value in values.items():
        if not isinstance(value,str) or not Path(value).is_absolute() or any(c in value for c in ["'",'\n','\r']):
            raise ValueError('无效的绝对路径：'+key)
        result[key]=Path(value).resolve()
    result.setdefault('stk_factor_pro_by_code',result['stk_factor_pro'].parent/'by_code')
    return result

PATHS=load_paths()

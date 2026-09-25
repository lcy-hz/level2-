"""Pure report HTML assembly shared by generator and legacy service."""
from pathlib import Path
import re

BASE=Path(__file__).resolve().parent


def add_detail_controls(html):
    html=re.sub(r'<!-- DETAIL START -->.*?<!-- DETAIL END -->','',html,flags=re.S)
    html=html.replace('盘中深查仅覆盖页面重点候选；全市场部分为日级聚合。',
                      '重点候选已预计算盘中深查；其余股票可在详情中点击计算当前报告日，结果缓存在本机。全市场历史部分仍为日级聚合。')
    feature=(BASE/'level2_detail_ui.html').read_text(encoding='utf-8')
    return html.replace('</body>','<!-- DETAIL START -->'+feature+'<!-- DETAIL END --></body>')

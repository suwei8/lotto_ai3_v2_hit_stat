# utils/db.py
import pymysql
import pandas as pd
import re
import os
import warnings
warnings.filterwarnings("ignore", category=UserWarning, message="pandas only supports SQLAlchemy.*")
from dotenv import load_dotenv
load_dotenv()

DB_CONFIG = {
    'host': os.getenv("MYSQL_HOST"),
    'port': int(os.getenv("MYSQL_PORT")),
    'user': os.getenv("MYSQL_USER"),
    'password': os.getenv("MYSQL_PASSWORD"),
    'database': os.getenv("MYSQL_DATABASE"),
    'charset': 'utf8mb4'
}



def get_connection():
    """获取数据库连接"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        return conn
    except pymysql.MySQLError as e:
        # 判断是否在 streamlit 环境，否则打印
        if "streamlit" in globals():
            st.error(f"数据库连接失败：{e}")
            st.stop()
        else:
            print(f"❌ 数据库连接失败：{e}")
            raise


# 给streamlit前台使用
def get_prediction_table(lottery_name: str) -> str:
    """根据彩票名称返回对应专家预测表"""
    mapping = {
        "福彩3D": "expert_predictions_3d",
        "排列3": "expert_predictions_p3",
        "排列5": "expert_predictions_p5",
        "快乐8": "expert_predictions_klb",
        "双色球": "expert_predictions_ssq",
        "大乐透": "expert_predictions_dlt",
    }
    return mapping.get(lottery_name, "expert_predictions_3d")  # 默认走福彩3D

def get_expert_info_table(lottery_name: str) -> str:
    """根据彩票名称返回对应专家信息表"""
    mapping = {
        "福彩3D": "expert_info_3d",
        "排列3": "expert_info_p3",
        "排列5": "expert_info_p5",
        "快乐8": "expert_info_klb",
        "双色球": "expert_info_ssq",
        "大乐透": "expert_info_dlt",
    }
    return mapping.get(lottery_name, "expert_info_3d")  # 默认走福彩3D


# 给采集脚本使用使用
def get_prediction_table_by_lottery_id(lottery_id: str) -> str:
    mapping = {
        "6": "expert_predictions_3d",      # 福彩3D
        "63": "expert_predictions_p3",     # 排列3
        "64": "expert_predictions_p5",     # 排列3
        "8": "expert_predictions_klb",     # 快乐8
        "5": "expert_predictions_ssq",     # 双色球
        "39": "expert_predictions_dlt",    # 大乐透
    }
    return mapping.get(str(lottery_id), "expert_predictions_3d")

def get_expert_info_table_by_lottery_id(lottery_id: str) -> str:
    mapping = {
        "6": "expert_info_3d",    # 福彩3D
        "63": "expert_info_p3",   # 排列3
        "64": "expert_info_p5",   # 排列5
        "8": "expert_info_klb",   # 快乐8
        "5": "expert_info_ssq",   # 双色球
        "39": "expert_info_dlt",  # 大乐透
    }
    return mapping.get(str(lottery_id), "expert_info_3d")

def get_result_table(lottery_name: str) -> str:
    """根据彩票名称返回对应开奖表"""
    mapping = {
        "福彩3D": "lottery_results_3d",
        "排列3": "lottery_results_p3",
        "排列5": "lottery_results_p5",
        "快乐8": "lottery_results_klb",
        "双色球": "lottery_results_ssq",
        "大乐透": "lottery_results_dlt",
    }
    return mapping.get(lottery_name, "lottery_results_3d")  # 默认走福彩3D

def get_user_ids_by_source_tags(conn, table_name: str, issue_name: str, source_tags: list[str]) -> list[str]:
    """
    根据来源标签，在指定期号内获取所有 user_id。
    可用于排除某些来源下的专家。
    """
    if not source_tags:
        return []

    query = f"""
        SELECT DISTINCT user_id
        FROM {table_name}
        WHERE issue_name = %s AND source_tag IN ({','.join(['%s'] * len(source_tags))})
    """
    df = pd.read_sql(query, conn, params=[issue_name, *source_tags])
    return df["user_id"].tolist()



def get_supported_lottery_names():
    """返回支持的彩票类型列表"""
    return ["福彩3D", "排列3","排列5", "快乐8", "双色球", "大乐透"]

def get_lottery_name_by_id(lottery_id: str) -> str:
    mapping = {
        "6": "福彩3D",
        "63": "排列3",
        "64": "排列5",
        "8": "快乐8",
        "5": "双色球",
        "39": "大乐透",
    }
    return mapping.get(str(lottery_id), "未知彩种")

# 支持蓝球字段的彩票类型
LOTTERIES_WITH_BLUE = {"双色球", "大乐透"}

def get_open_info(conn, result_table, issue_name, lottery_name=None):
    """
    获取指定期号的开奖号码（自动判断是否包含蓝球/后区，并封装展示函数）

    返回:
        dict {
            open_code: str,
            blue_code: str,
            open_nums: List[str],
            blue_nums: List[str],
            sum: int,
            span: int,
            odd_even_ratio: str,
            big_small_ratio: str,
            render: Callable[[], None]
        }
    """

    result_row = pd.read_sql(
        f"SELECT * FROM {result_table} WHERE issue_name = %s LIMIT 1",
        conn,
        params=[issue_name]
    )

    if result_row.empty:
        return {
            "open_code": "",
            "blue_code": "",
            "open_nums": [],
            "blue_nums": [],
            "sum": None,
            "span": None,
            "odd_even_ratio": "",
            "big_small_ratio": "",
            "render": lambda: st.warning("未找到该期开奖号码")
        }

    row = result_row.iloc[0]
    open_code = row.get("open_code", "")
    blue_code = row.get("blue_code", "") if lottery_name in LOTTERIES_WITH_BLUE else ""
    open_nums = list(map(int, re.findall(r"\d+", open_code)))
    blue_nums = list(map(int, re.findall(r"\d+", blue_code))) if blue_code else []

    # ✅ 扩展字段
    total_sum = sum(open_nums) if open_nums else None
    span = max(open_nums) - min(open_nums) if open_nums else None
    odd_count = sum(1 for n in open_nums if n % 2 == 1)
    even_count = len(open_nums) - odd_count
    odd_even_ratio = f"{odd_count}:{even_count}"

    half = 5  # 默认分界点，5及以下为小，6及以上为大（3D/排列类）
    big_count = sum(1 for n in open_nums if n > half)
    small_count = len(open_nums) - big_count
    big_small_ratio = f"{big_count}:{small_count}"

    # ✅ 渲染展示组件
    def render_open_result():
        blue_part = (
            f"""　<span style="color:#1890ff">🔵 蓝球/后区：</span>
                <code style="color:#1890ff">{blue_code}</code>"""
            if blue_code else ""
        )

        st.markdown(
            f"""
            <div style="font-size:20px; margin-top:10px; margin-bottom:10px;">
                <strong>🎯 第 <code>{issue_name}</code> 期开奖号码：</strong>
                <code style="color:green">{open_code}</code>{blue_part}　
                | 和值：<code>{total_sum}</code>　
                | 跨度：<code>{span}</code>　
                | 奇偶比：<code>{odd_even_ratio}</code>　
                | 大小比：<code>{big_small_ratio}</code>
            </div>
            """,
            unsafe_allow_html=True
        )



    return {
        "open_code": open_code,
        "blue_code": blue_code,
        "open_nums": open_nums,
        "blue_nums": blue_nums,
        "sum": total_sum,
        "span": span,
        "odd_even_ratio": odd_even_ratio,
        "big_small_ratio": big_small_ratio,
        "render": render_open_result
    }

def get_hit_stat_table(lottery_name: str) -> str:
    mapping = {
        "福彩3D": "expert_hit_stat_3d",
        "排列3": "expert_hit_stat_p3",
        "排列5": "expert_hit_stat_p5",
        "快乐8": "expert_hit_stat_klb",
        "双色球": "expert_hit_stat_ssq",
        "大乐透": "expert_hit_stat_dlt",
    }
    return mapping.get(lottery_name, "expert_hit_stat_3d")


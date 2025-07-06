"""
init_expert_hit_stat.py

📌 功能：
- 使用现成 utils/db.py 和 utils/hit_rule.py
- 按彩种分表生成专家命中汇总（expert_hit_stat_xxx）
- 支持 All / Today / 单期
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd


from utils.db import (
    get_connection,
    get_prediction_table,
    get_result_table,
    get_hit_stat_table,
    LOTTERIES_WITH_BLUE
)
from utils.hit_rule import match_hit

def ensure_hit_stat_table_exists(conn, table_name: str):
    """
    检查指定表是否存在，如果不存在则自动创建。
    表结构：
      - id：自增主键
      - issue_name：期号
      - user_id：专家ID
      - playtype_name：玩法名
      - total_count：预测记录总数
      - hit_count：命中期数
      - hit_number_count：命中数字数量
      - avg_hit_gap：平均命中间隔
      - 唯一索引：期号 + 专家ID + 玩法名
    """
    with conn.cursor() as cursor:
        # 🔍 检查表是否存在
        cursor.execute(f"SHOW TABLES LIKE %s", (table_name,))
        result = cursor.fetchone()
        if result:
            print(f"✅ 已存在：{table_name}")
            return

        # ⚙️ 不存在则新建表
        sql = f"""
        CREATE TABLE {table_name} (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增ID',
            issue_name VARCHAR(32) NOT NULL COMMENT '期号',
            user_id INT NOT NULL COMMENT '专家ID',
            playtype_name VARCHAR(64) NOT NULL COMMENT '玩法名称',
            total_count INT DEFAULT 0 COMMENT '总记录数',
            hit_count INT DEFAULT 0 COMMENT '命中期数',
            hit_number_count INT DEFAULT 0 COMMENT '命中数字数量',
            avg_hit_gap FLOAT DEFAULT NULL COMMENT '平均命中间隔',
            UNIQUE KEY uq_issue_user_playtype (issue_name, user_id, playtype_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='专家命中汇总表';
        """
        cursor.execute(sql)
        print(f"✅ 已新建表：{table_name}")

    conn.commit()


def update_hit_stat(lottery_name: str, issue_name: str):
    conn = get_connection()
    prediction_table = get_prediction_table(lottery_name)
    result_table = get_result_table(lottery_name)
    hit_stat_table = get_hit_stat_table(lottery_name)

    # ✅ 判断彩种是否包含蓝球
    select_cols = "open_code"
    if lottery_name in LOTTERIES_WITH_BLUE:
        select_cols += ", blue_code"

    open_df = pd.read_sql(
        f"SELECT {select_cols} FROM {result_table} WHERE issue_name = %s",
        conn, params=[issue_name]
    )
    if open_df.empty:
        print(f"⚠️ 未找到开奖号码：{issue_name}")
        conn.close()
        return

    open_code = open_df.iloc[0]["open_code"]
    blue_code = open_df.iloc[0].get("blue_code", "")

    # ✅ 查推荐
    df = pd.read_sql(
        f"""
        SELECT user_id, playtype_name, numbers
        FROM {prediction_table}
        WHERE issue_name = %s
        """,
        conn, params=[issue_name]
    )
    if df.empty:
        print(f"⚠️ 无推荐记录：{issue_name}")
        conn.close()
        return

    stat_list = []

    for (user_id, playtype_name), group in df.groupby(["user_id", "playtype_name"]):
        total_count = len(group)
        hit_count = 0
        hit_number_count = 0

        for _, row in group.iterrows():
            if match_hit(playtype_name, row["numbers"], open_code, blue_code):
                hit_count += 1

            open_nums = set(map(int, open_code.split(",")))
            pred_nums = set(int(n) for n in row["numbers"].split(",") if n.strip().isdigit())
            hit_number_count += len(open_nums & pred_nums)

        avg_hit_gap = round(total_count / hit_count, 2) if hit_count else None

        stat_list.append({
            "issue_name": issue_name,
            "user_id": user_id,
            "playtype_name": playtype_name,
            "total_count": total_count,
            "hit_count": hit_count,
            "hit_number_count": hit_number_count,
            "avg_hit_gap": avg_hit_gap
        })

    print(f"📌 期号：{issue_name} - 生成 {len(stat_list)} 条")

    with conn.cursor() as cursor:
        for row in stat_list:
            cursor.execute(
                f"""
                INSERT INTO {hit_stat_table}
                (issue_name, user_id, playtype_name,
                 total_count, hit_count, hit_number_count, avg_hit_gap)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    total_count = VALUES(total_count),
                    hit_count = VALUES(hit_count),
                    hit_number_count = VALUES(hit_number_count),
                    avg_hit_gap = VALUES(avg_hit_gap)
                """,
                (
                    row["issue_name"],
                    row["user_id"],
                    row["playtype_name"],
                    row["total_count"],
                    row["hit_count"],
                    row["hit_number_count"],
                    row["avg_hit_gap"]
                )
            )
    conn.commit()
    conn.close()
    print(f"✅ 已写入：{hit_stat_table} / {issue_name}")


def run_all(lottery_name: str):
    conn = get_connection()
    prediction_table = get_prediction_table(lottery_name)
    issue_df = pd.read_sql(
        f"SELECT DISTINCT issue_name FROM {prediction_table} ORDER BY issue_name ASC",
        conn
    )
    all_issues = issue_df["issue_name"].tolist()
    conn.close()

    print(f"🚀 [{lottery_name}] 共找到 {len(all_issues)} 期，开始全量...")
    for idx, issue in enumerate(all_issues, 1):
        print(f"\n=== [{idx}/{len(all_issues)}] 期号：{issue} ===")
        update_hit_stat(lottery_name, issue)


def run_today(lottery_name: str):
    conn = get_connection()
    prediction_table = get_prediction_table(lottery_name)
    result_table = get_result_table(lottery_name)
    hit_stat_table = get_hit_stat_table(lottery_name)

    open_df = pd.read_sql(
        f"SELECT DISTINCT issue_name FROM {result_table}",
        conn
    )
    open_issues = set(open_df["issue_name"].tolist())

    pred_df = pd.read_sql(
        f"SELECT DISTINCT issue_name FROM {prediction_table}",
        conn
    )
    pred_issues = set(pred_df["issue_name"].tolist())

    stat_df = pd.read_sql(
        f"SELECT DISTINCT issue_name FROM {hit_stat_table}",
        conn
    )
    stat_issues = set(stat_df["issue_name"].tolist())

    todo_issues = sorted(list(open_issues & pred_issues - stat_issues))
    print(f"🚦 [{lottery_name}] 待增量 {len(todo_issues)}：{todo_issues}")

    for idx, issue in enumerate(todo_issues, 1):
        print(f"\n=== [{idx}/{len(todo_issues)}] 增量期号：{issue} ===")
        update_hit_stat(lottery_name, issue)

    conn.close()

if __name__ == "__main__":
    # ✅ 先获取连接
    conn = get_connection()

    # 🔄 遍历所有目标彩种，逐个确保汇总表存在
    for LOTTERY_NAME in ["福彩3D", "排列3", "排列5", "快乐8", "双色球", "大乐透"]:
        hit_stat_table = get_hit_stat_table(LOTTERY_NAME)
        ensure_hit_stat_table_exists(conn, hit_stat_table)

    conn.close()

    # ✅ 再根据参数跑全量、增量或单期
    if len(sys.argv) < 2:
        print("❌ 缺少参数：python scripts/init_expert_hit_stat.py [All|Today|期号]")
        sys.exit(1)

    arg = sys.argv[1]

    LOTTERY_LIST = ["福彩3D", "排列3", "排列5", "快乐8", "双色球", "大乐透"]

    if arg == "All":
        for LOTTERY_NAME in LOTTERY_LIST:
            run_all(LOTTERY_NAME)
    elif arg == "Today":
        for LOTTERY_NAME in LOTTERY_LIST:
            run_today(LOTTERY_NAME)
    elif arg.isdigit():
        LOTTERY_NAME = "福彩3D"
        update_hit_stat(LOTTERY_NAME, arg)
    else:
        print(f"❌ 不支持参数：{arg}")

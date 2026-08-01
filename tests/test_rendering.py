"""Verify endpoint-specific Chinese presentation contracts."""

from __future__ import annotations

from astrbot_plugin_jx3tools.endpoints import ENDPOINT_INDEX
from astrbot_plugin_jx3tools.rendering import (
    build_article_document,
    build_document,
    card_identity,
    format_text,
    item_search_names,
)


def _rows(document) -> dict[str, str]:
    return {
        row.label: row.value
        for section in document.sections
        for card in section.cards
        for row in card.rows
    }


def test_daily_fields_follow_feedback_mapping() -> None:
    document = build_document(
        ENDPOINT_INDEX["active.calendar"],
        {
            "war": "大战本",
            "battle": "战场名",
            "orecar": "矿车",
            "school": "门派事件",
            "rescue": "不应展示",
            "draw": "美人图",
            "luck": ["宠物一", "宠物二"],
            "card": ["周常一", "周常二"],
            "team": [["公共一", "公共二"], ["大周常一"]],
        },
        max_items=30,
    )
    rows = _rows(document)

    assert rows["大战"] == "大战本"
    assert rows["福缘宠物"] == "宠物一\n宠物二"
    assert rows["武林通鉴·公共任务"] == "公共一\n公共二"
    assert rows["大周常"] == "大周常一"
    assert "rescue" not in str(document)
    assert "不应展示" not in str(document)


def test_role_merges_server_and_omits_internal_ids() -> None:
    document = build_document(
        ENDPOINT_INDEX["role.detail"],
        {
            "zoneName": "双线区",
            "serverName": "天鹅坪",
            "roleName": "侠士",
            "roleId": "123",
            "globalId": "456",
            "forceName": "万花",
            "forceId": 2,
            "bodyName": "成女",
            "bodyId": 1,
            "tongName": "测试帮会",
            "tongId": 9,
            "campName": "浩气盟",
            "campId": 1,
        },
        max_items=30,
    )
    rows = _rows(document)

    assert rows["区服"] == "双线区-天鹅坪"
    assert rows["角色 ID"] == "123"
    assert rows["全局 ID"] == "456"
    assert "forceId" not in str(document)
    assert "bodyId" not in str(document)
    assert "tongId" not in str(document)
    assert "campId" not in str(document)


def test_matrix_sorts_levels_one_to_six_and_omits_closed_effect() -> None:
    document = build_document(
        ENDPOINT_INDEX["school.matrix"],
        {
            "name": "太虚剑意",
            "skillName": "九宫八卦阵",
            "data": [
                {"level": 6, "name": "六层", "desc": "六层效果"},
                {"level": 0, "name": "闭阵", "desc": "不要展示"},
                {"level": 1, "name": "一层", "desc": "一层效果"},
            ],
        },
        max_items=30,
    )
    rows = _rows(document)

    assert rows["心法"] == "太虚剑意"
    assert rows["阵眼名称"] == "九宫八卦阵"
    assert rows["1"] == "一层效果"
    assert rows["6"] == "六层效果"
    assert "一层" not in rows
    assert "六层" not in rows
    assert "闭阵" not in str(document)


def test_smite_uses_chinese_labels_and_beijing_time() -> None:
    document = build_document(
        ENDPOINT_INDEX["smite.records"],
        [{"id": 9, "zone": "双线区", "server": "天鹅坪", "map_name": "洛道", "time": 0}],
        max_items=30,
    )
    serialized = str(document)

    assert "地图" in serialized
    assert "1970-01-01 08:00:00" in serialized
    assert "id" not in _rows(document)


def test_mech_has_no_generic_overview_or_item_number() -> None:
    document = build_document(
        ENDPOINT_INDEX["mech.calculator"],
        {
            "curr": {"node": "乾", "data": "一三五"},
            "next": {"node": "坤", "data": "二四六"},
            "time": "12:00",
            "cdtn": "条件",
        },
        max_items=30,
    )
    serialized = str(document)

    assert "副本·一之窟解密玩法" in serialized
    assert "当前" in serialized
    assert "下一时段" in serialized
    assert "概要" not in serialized
    assert "第 1 项" not in serialized


def test_forced_text_and_card_output_never_expose_urls() -> None:
    assert (
        format_text(
            ENDPOINT_INDEX["saohua.random"],
            {"id": 1, "text": "清风明月"},
            max_items=30,
        )
        == "清风明月"
    )
    card = {
        "zoneName": "双线区",
        "serverName": "天鹅坪",
        "roleName": "侠士",
        "showAvatar": "https://www.jx3api.com/card.png",
    }
    assert card_identity(card) == (
        "双线区-天鹅坪",
        "侠士",
        "https://www.jx3api.com/card.png",
    )
    text = format_text(ENDPOINT_INDEX["card.record"], card, max_items=30)
    assert text == "区服：双线区-天鹅坪\n角色名：侠士"
    assert "http" not in text


def test_article_parser_drops_active_content_and_links() -> None:
    document = build_article_document(
        {
            "title": "维护公告",
            "date": "2026-07-18",
            "content": (
                "<script>alert(1)</script><h2>更新说明</h2>"
                "<p>服务器维护完成。</p><a href='https://example.com'>点击链接</a>"
            ),
        }
    )
    serialized = str(document)

    assert "alert" not in serialized
    assert "服务器维护完成" in serialized
    assert "https://" not in serialized


def test_article_parser_does_not_restore_active_only_content() -> None:
    document = build_article_document(
        {
            "title": "维护公告",
            "date": "2026-08-01",
            "content": "<script>alert(1)</script><style>body{display:none}</style>",
        }
    )

    assert document.paragraphs == ("正文暂不可用。",)
    assert "alert" not in str(document)


def test_monthly_calendar_is_sunday_first_and_only_keeps_war_battle() -> None:
    document = build_document(
        ENDPOINT_INDEX["月历"],
        {
            "today": {"date": "2026-07-19"},
            "data": [
                {
                    "date": "2026-07-19",
                    "week": "星期日",
                    "war": "大战甲",
                    "battle": "战场甲",
                    "school": "不展示",
                },
                {"date": "2026-07-31", "war": "大战乙", "battle": "战场乙"},
                {"date": "2026-08-01", "war": "大战丙", "battle": "战场丙"},
            ],
        },
        max_items=1,
    )

    assert document.subtitle == "2026 · 前后各 15 天"
    assert document.calendar_days[0].value.weekday() == 6
    assert document.calendar_days[0].is_today
    assert document.calendar_days[1].month_label == "7月"
    assert document.calendar_days[2].month_label == "8月"
    assert "不展示" not in str(document)


def test_celebs_top_three_exam_fields_and_food_order() -> None:
    celebs = build_document(
        ENDPOINT_INDEX["行侠"],
        [
            {"map": f"地图{index}", "site": f"位置{index}"}
            for index in range(5)
        ],
        max_items=30,
    )
    assert len(celebs.sections[0].cards) == 3
    assert "位置" in _rows(celebs)

    exam = build_document(
        ENDPOINT_INDEX["科举"],
        [{"question": "古琴有几根弦", "answer": "七根", "correctness": 1, "index": 2, "pinyin": "GQ"}],
        max_items=30,
    )
    assert "七根" in str(exam)
    assert "correctness" not in str(exam)
    assert "pinyin" not in str(exam)

    foods = build_document(
        ENDPOINT_INDEX["小药"],
        [
            {"school": "天策", "kungfu": "铁牢律", "name": "包子", "boost": "外防"},
            {"school": "天策", "kungfu": "傲血战意", "name": "汤", "boost": "外功"},
            {
                "school": "无相楼",
                "kungfu": "幽罗引",
                "name": "长名称小药",
                "boost": "属性提升",
            },
        ],
        max_items=30,
    )
    assert [row.kungfu for row in foods.food_rows] == ["傲血战意", "铁牢律", "幽罗引"]
    assert foods.food_rows[0].items == ("汤（外功）",)
    assert foods.food_rows[0].school_color
    assert foods.food_rows[0].kungfu_color
    wuxiang = next(row for row in foods.food_rows if row.kungfu == "幽罗引")
    assert wuxiang.school_color == wuxiang.kungfu_color == "#806bb8"


def test_tianluo_foods_keep_every_unique_api_item_beyond_global_limit() -> None:
    payload = [
        {
            "school": "唐门",
            "kungfu": "天罗诡道",
            "name": f"小药{index}",
            "boost": "内功",
        }
        for index in range(9)
    ]
    payload.append(dict(payload[-1]))

    foods = build_document(
        ENDPOINT_INDEX["小药"],
        payload,
        max_items=1,
    )

    tianluo = next(row for row in foods.food_rows if row.kungfu == "天罗诡道")
    assert len(tianluo.items) == 9
    assert tianluo.items[-1] == "小药8（内功）"


def test_event_records_are_borderless_grids_and_drop_pet_adventures() -> None:
    document = build_document(
        ENDPOINT_INDEX["奇遇记录"],
        [
            {"event": "茶馆奇缘", "level": 1, "time": 0, "zone": "不展示"},
            {"event": "三山四海", "level": 2, "time": 1},
            {"event": "宠物奇遇", "level": 3, "time": 2},
        ],
        max_items=1,
    )

    assert [group.title for group in document.adventure_groups] == [
        "普通奇遇",
        "绝世奇遇",
    ]
    assert all(
        group.items[0].icon_asset.startswith("adventures/")
        for group in document.adventure_groups
    )
    assert "宠物奇遇" not in str(document)
    assert "不展示" not in str(document)


def test_arena_recent_gold_role_monster_and_trade_records_are_processed() -> None:
    arena = build_document(
        ENDPOINT_INDEX["名剑战绩"],
        {
            "zoneName": "双线区",
            "serverName": "天鹅坪",
            "roleName": "侠士",
            "forceName": "万花",
            "performance": {
                "3v3": {"mmr": 2200, "grade": 12, "ranking": 10, "winCount": 8, "totalCount": 10, "mvpCount": 3}
            },
            "history": [{"startTime": 0, "pvpType": 3, "kungfu": "花间游", "won": 1, "mmr": 12, "totalMmr": 2200}],
        },
        max_items=30,
    )
    assert arena.chart_entries[0].value == 80
    assert arena.chart_entries[0].label == "3V3"
    assert arena.sections[0].columns == 3
    assert arena.sections[0].profile_layout
    assert arena.tables[0].rows[0].cells[1].text == "3V3 · 花间游"
    assert arena.tables[0].rows[0].cells[3].accent_text == "+12"
    assert arena.tables[0].rows[0].cells[3].accent_color == "#d52b1e"
    assert arena.tables[0].headers == ("时间", "模式 / 心法", "结果", "积分")

    gold = build_document(
        ENDPOINT_INDEX["金价"],
        [
            {"date": f"2026-07-{day:02d}", "tieba": day, "wanbaolou": day + 1, "dd373": 0}
            for day in range(1, 16)
        ],
        max_items=3,
    )
    assert len(gold.line_series) == 2
    assert all(len(series.points) == 15 for series in gold.line_series)

    role_monster = build_document(
        ENDPOINT_INDEX["角色百战"],
        {"zone": "双线区", "server": "天鹅坪", "roleName": "侠士", "skill_stamina": 90, "skill_energy": 80, "skill_count": 7, "extra": "不展示"},
        max_items=30,
    )
    assert set(_rows(role_monster)) == {"区服", "角色", "体力", "精力", "技能数量"}

    trade = build_document(
        ENDPOINT_INDEX["物价"],
        {
            "name": "十五夜观灯·南涧·标准",
            "class": "外观礼盒",
            "view": "https://nico.nicemoe.cn/item.png",
            "list": [[{"zone": "双线区", "server": "天鹅坪", "sale": 1, "value": 100, "date": "2026-07-19", "token": "secret"}]],
        },
        max_items=30,
    )
    assert "最低 100" in str(trade)
    assert "物品摘要" not in str(trade)
    assert trade.icon_url == "https://nico.nicemoe.cn/item.png"
    assert trade.tables[0].rows[0].cells[1].text == "出售"
    assert "secret" not in str(trade)


def test_item_search_names_and_view_are_preserved_for_copying_and_hero_image() -> None:
    data = [
        {
            "name": "物品甲",
            "view": "https://nico.nicemoe.cn/item.png",
            "class": "材料",
        },
        {"name": "物品乙", "class": "材料"},
    ]
    document = build_document(
        ENDPOINT_INDEX["物品搜索"],
        data,
        max_items=30,
    )

    assert item_search_names(data) == "物品甲\n物品乙"
    assert document.icon_url == "https://nico.nicemoe.cn/item.png"
    assert document.hero_image_width == 600


def test_item_search_names_filter_urls_and_enforce_character_limit() -> None:
    data = [
        {"name": "https://attacker.example/secret"},
        *({"name": f"可复制物品{index:03d}"} for index in range(100)),
    ]

    names = item_search_names(data, max_characters=96)

    assert "attacker.example" not in names
    assert len(names) <= 96
    assert names.endswith("……名称列表已截断")


def test_mech_and_chitu_empty_results_are_copyable_text() -> None:
    mech = format_text(
        ENDPOINT_INDEX["解密"],
        {"now_node": "乾", "now_result": "一三五", "next_node": "坤", "next_result": "二四六", "cdtn": "不展示"},
        max_items=30,
    )
    assert mech == "【解密】\n当前：乾：一三五\n下一时段：坤：二四六"
    assert format_text(ENDPOINT_INDEX["今日赤兔"], {}, max_items=30) == "今日暂无赤兔记录。"
    assert format_text(ENDPOINT_INDEX["本周赤兔"], {}, max_items=30) == "本周暂无赤兔记录。"

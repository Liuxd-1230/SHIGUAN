"""
生成 Phase 1A 的 Mock 数据（fixtures/mock/*.json）。

本脚本直接复用 packages/save-schema/py/models.py 的 Pydantic 契约来构造数据，
因此产出的 JSON 必然符合数据契约，且全部用 FixtureEnvelope 包裹（isMock: true），
绝不与真实存档解析结果混淆。

产物：
  - arnulf.json   : FixtureEnvelope[CharacterProfile]  —— 一名封建公爵
  - lowborn.json  : FixtureEnvelope[CharacterProfile]  —— 一名无头衔低微人物
  - index.json    : FixtureEnvelope[MockDataset]        —— 选择页用的索引包
                     （characterIndex: CharacterSummary[] + profiles: Record<id, CharacterProfile>）

运行：
  python scripts/gen_mock.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "save-schema", "py"))

from models import (  # noqa: E402
    BiographyStyle,
    CharacterProfile,
    CharacterRef,
    CharacterSummary,
    Confidence,
    EntityRef,
    EvidenceRef,
    EvidenceWarning,
    EventType,
    FixtureEnvelope,
    LifeEvent,
    MockDataset,
    MockDatasetPayload,
    MockIndex,
    MockIndexPayload,
    ParsedSaveMeta,
    PositionPeriod,
    RelationshipPeriod,
    RelationshipType,
    ResidencePeriod,
    Sex,
    TitlePeriod,
    TitleTier,
    TimelineEvent,
    TraitRecord,
    WarParticipation,
    WarRole,
)

SCHEMA_VERSION = "0.5.0"
FIXTURE_DIR = os.path.join(ROOT, "fixtures", "mock")


def ev(ref_id, source_type, description, confidence, source_path=None, raw_key=None, related=None):
    return EvidenceRef(
        id=ref_id,
        sourceType=source_type,
        sourcePath=source_path,
        rawKey=raw_key,
        description=description,
        confidence=confidence,
        relatedEventId=related,
    )


def build_arnulf() -> CharacterProfile:
    dynasty = EntityRef(id="dyn_hohenwerth", name="霍恩韦尔特王朝", type="dynasty")
    house = EntityRef(id="hou_werth", name="韦尔特家族", type="house")
    culture = EntityRef(id="culture_franconian", name="法兰克尼亚文化", type="culture")
    faith = EntityRef(id="faith_catholic", name="天主教", type="faith")
    duchy = EntityRef(id="d_werth", name="韦尔特公国", type="title")
    kingdom = EntityRef(id="k_francia", name="法兰克王国", type="title")

    father = CharacterRef(
        id="folker", name="福尔克尔", sex=Sex.MALE, birthDate="1005.02.01",
        deathDate="1070.08.19", dynasty=dynasty, primaryTitle=duchy,
    )
    child1 = CharacterRef(id="heinrich", name="海因里希", sex=Sex.MALE, birthDate="1057.05.30", dynasty=dynasty, primaryTitle=duchy)
    child2 = CharacterRef(id="elisabeth", name="伊丽莎白", sex=Sex.FEMALE, birthDate="1061.09.12", dynasty=dynasty)
    sibling = CharacterRef(id="konrad", name="康拉德", sex=Sex.MALE, birthDate="1035.01.10", deathDate="1081.03.02", dynasty=dynasty)
    friend = CharacterRef(id="bishopsieg", name="西格主教", sex=Sex.MALE, birthDate="1028.11.01", faith=faith)
    rival = CharacterRef(id="duke_otto", name="奥托公爵", sex=Sex.MALE, birthDate="1030.06.06", dynasty=EntityRef(id="dyn_neighbour", name="邻邦王朝", type="dynasty"))

    timeline = [
        TimelineEvent(
            id="ev_birth", type=EventType.BIRTH, date="1032.04.12", title="诞生于韦尔特",
            description="阿努尔夫生于法兰克尼亚的韦尔特城堡，为福尔克尔长子。",
            confidence=Confidence.CONFIRMED,
            evidence=[ev("e_birth", "save_block", "人物块记录出生日期与父亲", Confidence.CONFIRMED, "character/arnulf/birth", "birth")],
        ),
        TimelineEvent(
            id="ev_marry1", type=EventType.MARRIAGE, date="1055.06.20", title="与格特鲁德联姻",
            description="为巩固东方边疆，阿努尔夫迎娶格特鲁德。",
            confidence=Confidence.CONFIRMED,
            evidence=[ev("e_marry1", "save_block", "配偶关系块记录", Confidence.CONFIRMED, "character/arnulf/spouse/0", "spouse")],
        ),
        TimelineEvent(
            id="ev_title_duchy", type=EventType.TITLE_GAIN, date="1065.01.01", title="继承韦尔特公国",
            description="父亲去世后，阿努尔夫继承韦尔特公国，成为一方诸侯。",
            confidence=Confidence.CONFIRMED,
            evidence=[ev("e_duchy", "save_block", "头衔持有块", Confidence.CONFIRMED, "character/arnulf/title/d_werth", "d_werth")],
        ),
        TimelineEvent(
            id="ev_child1", type=EventType.CHILD_BIRTH, date="1057.05.30", title="长子海因里希出生",
            description="与格特鲁德的长子海因里希降生。",
            confidence=Confidence.CONFIRMED,
            evidence=[ev("e_child1", "save_block", "子女关系块", Confidence.CONFIRMED, "character/arnulf/children/0")],
        ),
        TimelineEvent(
            id="ev_war1", type=EventType.WAR, date="1088.03.01", title="发动继承战争",
            description="为争夺法兰克王位，阿努尔夫以进攻方身份卷入继承战争。",
            confidence=Confidence.CONFIRMED,
            evidence=[ev("e_war1", "war", "战争参与块记录为 attacker", Confidence.CONFIRMED, "war/war_001/participants", "war_001")],
        ),
        TimelineEvent(
            id="ev_king", type=EventType.SUCCESSION, date="1088.09.01", title="加冕为法兰克国王",
            description="继承战争胜利后，阿努尔夫短暂戴上法兰克王冠。",
            confidence=Confidence.CONFIRMED,
            evidence=[ev("e_king", "save_block", "头衔持有块（王国）", Confidence.CONFIRMED, "character/arnulf/title/k_francia", "k_francia")],
        ),
        TimelineEvent(
            id="ev_king_lost", type=EventType.TITLE_LOSS, date="1094.02.15", title="失去法兰克王位",
            description="因联盟瓦解，阿努尔夫被迫放弃王冠，退回公国。",
            confidence=Confidence.CONFIRMED,
            evidence=[ev("e_king_lost", "save_block", "头衔结束日期", Confidence.CONFIRMED, "character/arnulf/title/k_francia/end")],
        ),
        TimelineEvent(
            id="ev_death", type=EventType.DEATH, date="1098.11.03", title="于韦尔特辞世",
            description="阿努尔夫在韦尔特城堡安然离世，享年六十六。",
            confidence=Confidence.CONFIRMED,
            evidence=[ev("e_death", "save_block", "人物死亡日期与死因", Confidence.CONFIRMED, "character/arnulf/death", "death")],
        ),
    ]

    return CharacterProfile(
        id="arnulf_001", name="阿努尔夫", sex=Sex.MALE, birthDate="1032.04.12", deathDate="1098.11.03",
        deathReason="年老辞世", dynasty=dynasty, house=house, culture=culture, faith=faith,
        traits=[
            TraitRecord(id="trait_brave", name="勇敢", category="personality"),
            TraitRecord(id="trait_ambitious", name="野心勃勃", category="personality"),
            TraitRecord(id="trait_fertile", name="多产", category="health"),
        ],
        titles=[
            TitlePeriod(titleId="c_ostmark", name="东边疆区", tier=TitleTier.COUNTY, start="1058.03.10", end="1071.06.20", isCurrent=False, government="feudal"),
            TitlePeriod(titleId="d_werth", name="韦尔特公国", tier=TitleTier.DUCHY, start="1065.01.01", end=None, isCurrent=True, government="feudal"),
            TitlePeriod(titleId="k_francia", name="法兰克王国", tier=TitleTier.KINGDOM, start="1088.09.01", end="1094.02.15", isCurrent=False, government="feudal"),
        ],
        residences=[
            ResidencePeriod(locationId="b_werth_castle", name="韦尔特城堡", start="1065.01.01", confidence=Confidence.CONFIRMED, sourcePath="character/arnulf/capital"),
            ResidencePeriod(locationId="c_ostmark", name="东边疆区首府", start="1058.03.10", end="1071.06.20", confidence=Confidence.INFERRED, sourcePath="character/arnulf/title/c_ostmark"),
        ],
        courtPositions=[
            PositionPeriod(courtId="k_francia", courtName="法兰克宫廷", positionId="pos_spymaster", name="间谍大师", start="1089.01.01", end="1092.12.31", employerId="arnulf_001"),
        ],
        parents=[father],
        spouses=[
            RelationshipPeriod(characterId="gertrude", name="格特鲁德", type=RelationshipType.SPOUSE, start="1055.06.20", end="1077.04.10", confidence=Confidence.CONFIRMED),
            RelationshipPeriod(characterId="beatrix", name="贝亚特丽克丝", type=RelationshipType.SPOUSE, start="1079.08.15", end=None, confidence=Confidence.CONFIRMED),
        ],
        children=[child1, child2],
        siblings=[sibling],
        friends=[friend],
        rivals=[rival],
        lovers=[],
        wars=[
            WarParticipation(warId="war_001", name="继承战争", role=WarRole.ATTACKER, side="attacker", start="1088.03.01", end="1090.11.01", outcome="胜利", sourcePath="war/war_001"),
            WarParticipation(warId="war_002", name="边境冲突", role=WarRole.DEFENDER, side="defender", start="1093.05.01", end="1094.02.15", outcome="失利", sourcePath="war/war_002"),
        ],
        imprisonments=[],
        travels=[
            LifeEvent(id="tr_pilgrimage", type=EventType.TRAVEL, date="1072.04.01", description="疑似前往罗马朝圣（具体行程存疑）。", confidence=Confidence.UNCERTAIN, sourcePath="memory/arnulf/3"),
        ],
        memories=[
            LifeEvent(id="mem_crown", type=EventType.SUCCESS, date="1088.09.01", description="加冕之夜的记忆：钟声与欢呼。", confidence=Confidence.INFERRED, sourcePath="memory/arnulf/1"),
        ],
        timeline=timeline,
        evidenceWarnings=[
            EvidenceWarning(code="uncertain_travel", message="朝圣行程无明确记录，标记为不确定。", severity="info", relatedEventId="tr_pilgrimage", sourcePath="memory/arnulf/3"),
        ],
    )


def build_lowborn() -> CharacterProfile:
    culture = EntityRef(id="culture_franconian", name="法兰克尼亚文化", type="culture")
    faith = EntityRef(id="faith_catholic", name="天主教", type="faith")
    child = CharacterRef(id="lowborn_child", name="小玛蒂尔达", sex=Sex.FEMALE, birthDate="1068.02.14")

    timeline = [
        TimelineEvent(
            id="lb_birth", type=EventType.BIRTH, date="1041.07.02", title="生于农庄",
            description="玛蒂尔达出生于一处无名小农庄，父母姓名失载。",
            confidence=Confidence.CONFIRMED,
            evidence=[ev("lb_b", "save_block", "人物块记录出生", Confidence.CONFIRMED, "character/lowborn/birth", "birth")],
        ),
        TimelineEvent(
            id="lb_travel", type=EventType.TRAVEL, date="1062.03.01", title="疑似迁居城镇",
            description="约公元 1062 年，可能迁居邻近城镇谋生，行程无确证。",
            confidence=Confidence.UNCERTAIN,
            evidence=[ev("lb_t", "memory", "记忆片段，地点未证实", Confidence.UNCERTAIN, "memory/lowborn/2")],
        ),
        TimelineEvent(
            id="lb_child", type=EventType.CHILD_BIRTH, date="1068.02.14", title="女儿出生",
            description="玛蒂尔达的女儿降生，生父不详（由子女反推存在母亲）。",
            confidence=Confidence.INFERRED,
            evidence=[ev("lb_c", "save_block", "子女关系块反推母亲", Confidence.INFERRED, "character/lowborn/children/0")],
        ),
    ]

    return CharacterProfile(
        id="lowborn_002", name="玛蒂尔达", sex=Sex.FEMALE, birthDate="1041.07.02", deathDate=None,
        dynasty=None, house=None, culture=culture, faith=faith,
        traits=[TraitRecord(id="trait_content", name="知足", category="personality")],
        titles=[],
        residences=[
            ResidencePeriod(locationId="b_small_holding", name="小农庄", start="1060.01.01", confidence=Confidence.INFERRED, sourcePath="character/lowborn/residence"),
        ],
        courtPositions=[],
        parents=[],
        spouses=[],
        children=[child],
        siblings=[],
        friends=[],
        rivals=[],
        lovers=[],
        wars=[],
        imprisonments=[],
        travels=[
            LifeEvent(id="tr_move", type=EventType.TRAVEL, date="1062.03.01", description="疑似迁居，无确证。", confidence=Confidence.UNCERTAIN, sourcePath="memory/lowborn/2"),
        ],
        memories=[],
        timeline=timeline,
        evidenceWarnings=[
            EvidenceWarning(code="missing_localization", message="该人物王朝/家族未经本地化，名称可能不准确。", severity="warning", sourcePath="character/lowborn"),
        ],
    )


def summary_of(p: CharacterProfile, is_ruler: bool, is_alive: bool, is_player_dynasty: bool, primary_title: EntityRef | None, highest_tier: TitleTier | None) -> CharacterSummary:
    return CharacterSummary(
        id=p.id, name=p.name, sex=p.sex, birthDate=p.birthDate, deathDate=p.deathDate,
        dynasty=p.dynasty, house=p.house, culture=p.culture, faith=p.faith,
        primaryTitle=primary_title, highestTitleTier=highest_tier,
        isRuler=is_ruler, isAlive=is_alive, isPlayerDynasty=is_player_dynasty,
        portraitKey=None, evidenceWarningCount=len(p.evidenceWarnings),
    )


def write_json(name: str, obj) -> None:
    path = os.path.join(FIXTURE_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"  wrote {os.path.relpath(path, ROOT)}")


# 一个"故意无效"的档案：用于演示运行时校验在档案损坏时进入可读错误状态，
# 而非白屏。其时间线事件缺失 evidence 字段（契约要求 evidence 为数组）。
INCOMPLETE_PROFILE = {
    "isMock": True,
    "source": "fixtures/mock",
    "schemaVersion": SCHEMA_VERSION,
    "generatedFor": "phase-1b-boundary",
    "data": {
        "id": "incomplete_003",
        "name": "残缺档案·佚名",
        "sex": "male",
        "traits": [],
        "titles": [],
        "residences": [],
        "courtPositions": [],
        "parents": [],
        "spouses": [],
        "children": [],
        "siblings": [],
        "friends": [],
        "rivals": [],
        "lovers": [],
        "wars": [],
        "imprisonments": [],
        "travels": [],
        "memories": [],
        "timeline": [
            {
                "id": "ev_birth",
                "type": "birth",
                "title": "诞生",
                "description": "出生记录残缺，无法定位证据。",
                "confidence": "maybe",  # 故意非法枚举值：契约要求 confirmed/inferred/uncertain
                # 注意：同时缺失 evidence 字段，触发运行时校验失败
            }
        ],
        "evidenceWarnings": [],
    },
}


def main() -> None:
    profiles_dir = os.path.join(FIXTURE_DIR, "profiles")
    os.makedirs(profiles_dir, exist_ok=True)

    arnulf = build_arnulf()
    lowborn = build_lowborn()

    # 每个完整档案单独用 FixtureEnvelope<CharacterProfile> 包裹，放在 profiles/ 下，
    # 由前端 CharacterRepository 按需懒加载（import.meta.glob eager:false）。
    arnulf_env = FixtureEnvelope[CharacterProfile](
        schemaVersion=SCHEMA_VERSION, generatedFor="phase-1b-demo", data=arnulf,
    )
    lowborn_env = FixtureEnvelope[CharacterProfile](
        schemaVersion=SCHEMA_VERSION, generatedFor="phase-1b-demo", data=lowborn,
    )
    write_json(os.path.join("profiles", "arnulf_001.json"), arnulf_env.model_dump(mode="json"))
    write_json(os.path.join("profiles", "lowborn_002.json"), lowborn_env.model_dump(mode="json"))

    # 故意无效的档案（缺失 evidence），用于演示"档案加载失败"。
    with open(os.path.join(profiles_dir, "incomplete_003.json"), "w", encoding="utf-8") as f:
        json.dump(INCOMPLETE_PROFILE, f, ensure_ascii=False, indent=2)
    print(f"  wrote fixtures/mock/profiles/incomplete_003.json (intentionally invalid)")

    # 索引包：仅 Mock 元数据 + ParsedSaveMeta + 摘要索引 + 档案定位符（profileIds）。
    # 不内联完整 CharacterProfile，真正按需加载。
    index_payload = MockIndexPayload(
        meta=ParsedSaveMeta(
            saveVersion="mock-1.0.0",
            gameVersion="1.12.mock",
            date="1098.01.01",
            playerId="arnulf_001",
            campaignId="mock-campaign",
        ),
        characterIndex=[
            summary_of(arnulf, is_ruler=True, is_alive=False, is_player_dynasty=True,
                       primary_title=EntityRef(id="d_werth", name="韦尔特公国", type="title"),
                       highest_tier=TitleTier.KINGDOM),
            summary_of(lowborn, is_ruler=False, is_alive=True, is_player_dynasty=False,
                       primary_title=None, highest_tier=None),
            summary_of(incomplete_profile_obj(), is_ruler=False, is_alive=False, is_player_dynasty=False,
                       primary_title=None, highest_tier=None),
        ],
        profileIds=["arnulf_001", "lowborn_002", "incomplete_003"],
    )
    index_env = MockIndex(schemaVersion=SCHEMA_VERSION, generatedFor="phase-1b-demo", data=index_payload)

    print("生成 Mock 数据（均用 FixtureEnvelope 包裹，isMock=true）：")
    write_json("index.json", index_env.model_dump(mode="json"))
    print("完成。")


def incomplete_profile_obj() -> CharacterProfile:
    """构造一个摘要用的占位档案（其完整档案文件故意无效，用于演示加载失败）。"""
    return CharacterProfile(
        id="incomplete_003", name="残缺档案·佚名", sex=Sex.MALE,
        dynasty=None, house=None, culture=None, faith=None,
        traits=[], titles=[], residences=[], courtPositions=[],
        parents=[], spouses=[], children=[], siblings=[],
        friends=[], rivals=[], lovers=[], wars=[],
        imprisonments=[], travels=[], memories=[],
        timeline=[
            TimelineEvent(
                id="ev_birth", type=EventType.BIRTH, title="诞生（记录残缺）",
                description="出生记录残缺，无法定位证据。",
                confidence=Confidence.UNCERTAIN,
                evidence=[ev("e_missing", "memory", "记录残缺，证据缺失", Confidence.UNCERTAIN)],
            )
        ],
        evidenceWarnings=[
            EvidenceWarning(code="profile_corrupt", message="该人物完整档案损坏，无法载入。", severity="error"),
        ],
    )


if __name__ == "__main__":
    main()

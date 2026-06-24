"""Eine von Hand geschriebene Beispielmission.

Spaeter wuerde die GUI genau so ein Mission-Objekt zusammenklicken.
Hier dient es als Test, dass Modell -> Codegen -> DLL -> Spiel funktioniert.
"""
from mission_model import (
    Colony, Condition, Mission, MissionType, PlayerSpec, StartMessage, UnitSpec,
)


def build_demo() -> Mission:
    return Mission(
        name="Codegen Test Colony",
        map="cm02.map",
        tech_tree="MULTITEK.TXT",
        type=MissionType.Colony,
        num_players=1,
        players=[PlayerSpec(colony=Colony.Eden, tech_level=12, init_resources=True)],
        units=[
            UnitSpec("mapCommandCenter", x=64, y=72, player=0),
            UnitSpec("mapTokamak", x=67, y=72, player=0),
            UnitSpec("mapStructureFactory", x=64, y=75, player=0),
            UnitSpec("mapAgridome", x=67, y=75, player=0),
        ],
        start_message=StartMessage("Diese Mission wurde von Python generiert."),
        victories=[Condition(kind="time", marks=600, objective="Halte 600 Marks durch.")],
        defeats=[Condition(kind="noCC", player=0)],
    )

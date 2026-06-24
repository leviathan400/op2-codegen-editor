// === AUTO-GENERIERT vom Python-Codegen -- nicht von Hand editieren ===
#include <Outpost2DLL/Outpost2DLL.h>
#include <OP2Helper/OP2Helper.h>
#include <HFL/Source/HFL.h>

ExportLevelDetails("Editor Mission", "cm02.map", "MULTITEK.TXT", MissionTypes::Colony, 1)

struct ScriptGlobal { } scriptGlobal;
ExportSaveLoadData(scriptGlobal);

Export int InitProc()
{
	Player[0].GoEden();
	Player[0].GoHuman();
	Player[0].SetTechLevel(12);
	InitPlayerResources(0);

	AddGameMessage("Mit dem OP2 Mission Editor erstellt.");

	CreateTimeTrigger(1, 0, 10, "TrigCB_Trigger1");
	CreateTimeTrigger(1, 1, 500, "TrigCB_Trigger2");

	return true;
}

Export void AIProc() { }

Export void NoResponseToTrigger() { }

Export void TrigCB_Trigger1()
{
	bool cond_0_0 = false;
	{ UnitEx _cur; LOCATION _loc = MkXY(21, 21); PlayerBuildingEnum _e(0, mapCommandCenter);
	  while (_e.GetNext(_cur)) { if (_cur.Location() == _loc) { cond_0_0 = true; break; } } }
	if (cond_0_0) {
		AddGameMessage("CC da");
	}
}

Export void TrigCB_Trigger2()
{
	UnitEx u;
	TethysGame::CreateUnit(u, mapCommandCenter, MkXY(21, 21), 0, mapNone, 0);
}

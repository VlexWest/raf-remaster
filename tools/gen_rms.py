#!/usr/bin/env python3
"""Generate the three custom random map scripts into rms/.

Usage: python tools/gen_rms.py [outdir]      (default: <repo>/rms)

Every value below is an original design decision.  The only things taken from
the shipped scripts are the *names* of keywords, resources and includes
(checked by tools/lint_rms.py), and the numeric ranges that the shipped scripts
prove the generator accepts.  No shipped text is copied.

Maps (file name = name the exe lists, see docs/maps.md):
  archipelago.rmv   many small islands, naval focus, 2-8 players
  twin rivers.rmv   big land map, rivers with fords, teams on opposite sides
  uplands.rmv       open hill country with choke points, rich in resources
"""
import os
import sys

SIZES = ["Tiny", "Small", "Medium", "Large", "Huge"]
PLAYERS = [2, 3, 4, 5, 6, 7, 8]


def pick(arr, n):
    """arr is indexed by player count 2..8."""
    return arr[n - 2]


def btw(a, b=None):
    b = a if b is None else b
    return "Between(%s, %s)" % (a, b)


# --------------------------------------------------------------------------
# Archipelago
# --------------------------------------------------------------------------
def archipelago(n, s):
    land = [0.50, 0.42, 0.38, 0.36, 0.36][s] + (0.03 if n >= 6 else 0.0)
    n_in = max(1, [2, 4, 6, 8, 10][s] - (1 if n >= 5 else 0) - (1 if n >= 7 else 0))
    n_out = [0, 1, 2, 3, 4][s] if n <= 6 else max(0, [0, 0, 1, 2, 3][s])
    fish = [18, 22, 24, 26, 28][s] - (3 if n >= 6 else 0)
    d = {
        "kMinIntElevation": -10,
        "kMaxIntElevation": 8,
        "kElevationScale": 1,
        "kPercentLand": btw("%.2f" % land),
        "kWaterBorder": [0, 3, 4, 5, 6][s],
        "kRiverWidth": [6, 8, 8, 9, 9][s],
        "kCoastToDeepWaterPercentage": "1.0",
        "kHeightMapChaos": btw(10),
        "kMinimumStartPositionToMapEdge": 2,
        "kOuterPushFromMapCenter": 30,
        "kInnerPushFromMapCenter": 0,
        "kPeninsulaKiller": "0.05",
        "kMaxAngleBetweenTeamMembers": pick([40.0, 50.0, 70.0, 50.0, 50.0, 40.0, 40.0], n),
        "kPlayerInnerRadius": "0.7",
        "kPlayerOuterRadius": "0.85",
        "kPlayerPercentFlat": btw("0.9"),
        "kPlayerLandChaos": "0.8",
        "kPlayerLandClumps": 1,
        "kPlayerFlatChaos": "0.8",
        "kPlayerFlatClumps": 1,
        "kPlayerTreePercentage": "0.12",
        "kTileDistanceBetweenPlayers": pick([20.0, 17.0, 15.0, 5.0, 5.0, 5.0, 5.0], n),
        "kNeutralInnerRadius": "0.05",
        "kNeutralOuterRadius": "0.5",
        "kNumInnerNeutrals": btw(n_in),
        "kInnerNeutralPercentLand": "0.25",
        "kInnerNeutralPercentFlat": btw("0.8"),
        "kInnerNeutralTreePercentage": "0.1",
        "kInnerNeutralLandChaos": "0.8",
        "kInnerNeutralLandClumps": btw(1),
        "kInnerNeutralFlatChaos": "0.8",
        "kInnerNeutralFlatClumps": 1,
        "kNumOuterNeutrals": btw(n_out),
        "kOuterNeutralPercentLand": "0.3",
        "kOuterNeutralPercentFlat": btw("0.8"),
        "kOuterNeutralTreePercentage": "0.1",
        "kOuterNeutralLandChaos": "0.8",
        "kOuterNeutralLandClumps": 1,
        "kOuterNeutralFlatChaos": "0.8",
        "kOuterNeutralFlatClumps": 1,
        "kMaxResourceElevation": 2,
        "kResourceToEdgeDistance": 2,
        "kResourceToWaterDistance": 2,
        "kAnimalPerPlayer": 0,
        "kAnimalPerNeutral": 0,
        "kBerryPerNeutral": 0,
        "kFishPerPlayer": fish,
        "kFishPerNeutral": 0,
        "kGoldPerPlayer": [3, 4, 4, 4, 5][s],
        "kGoldPerNeutral": [2, 5, 8, 12, 16][s],
        "kStonePerPlayer": [1, 2, 2, 2, 2][s],
        "kStonePerNeutral": [1, 2, 3, 4, 5][s],
        "kTreePerPlayer": 2,
        "kTreePerNeutral": 0,
        "kForestFreeRadius": "6.0",
        "kForestsPerPlayer": [3, 4, 4, 4, 4][s],
        "kForestChaosLevel": "0.1",
        "kMaxClumpsPerForest": 2,
    }
    return d


def archipelago_n(n):
    return ["ResourceSeperation %d" % pick([7, 6, 6, 6, 6, 5, 5], n)]


def archipelago_s(s):
    g = [(5, 13), (5, 15), (6, 23), (7, 25), (7, 25)][s]
    st = [(5, 13), (5, 17), (6, 23), (7, 15), (7, 25)][s]
    fi = [40, 40, 45, 55, 55][s]
    return [
        "ResourcePlacementLimit (Gold, %d, %d)" % g,
        "ResourcePlacementLimit (Stone, %d, %d)" % st,
        "ResourcePlacementLimit (Berry, 3, 7)",
        "ResourcePlacementLimit (Fish, 1, %d)" % fi,
        "ResourcePlacementLimit (Tree, 4, 10)",
        "ResourcePlacementLimit (Animal, 7, 25)",
    ]


# --------------------------------------------------------------------------
# Twin Rivers
# --------------------------------------------------------------------------
def twin_rivers(n, s):
    big = s >= 3
    gold = pick([8, 7, 6, 6, 5, 5, 5], n) if big else pick([6, 5, 5, 4, 4, 4, 4], n)
    forests = pick([18, 14, 12, 10, 9, 8, 7], n) if big else pick([16, 14, 12, 10, 9, 8, 7], n)
    two = n == 2
    d = {
        "kMinIntElevation": -3,
        "kMaxIntElevation": 7,
        "kElevationScale": 1,
        "kPercentLand": btw("0.90"),
        "kWaterBorder": 0,
        "kRiverWidth": [8, 9, 10, 10, 10][s],
        "kCoastToDeepWaterPercentage": "1.0",
        "kHeightMapChaos": btw(8, 12),
        "kMinimumStartPositionToMapEdge": 2,
        "kOuterPushFromMapCenter": 30,
        "kInnerPushFromMapCenter": 0,
        "kShallowsElevation": "-0.5",
        "kShallowsWidth": 2,
        "kMaxShallowConnectionsPerPlayer": btw(3) if n <= 4 else btw(2, 3),
        "kTileDistanceBetweenShallows": [8, 8, 8, 10, 10][s],
        "kGenerateShallows": "true",
        "kPeninsulaKiller": "0.1",
        "kRiverLandFillWidth": 1,
        "kMaxAngleBetweenTeamMembers": pick([40.0, 50.0, 60.0, 50.0, 50.0, 40.0, 40.0], n),
        "kPlayerInnerRadius": "0.72",
        "kPlayerOuterRadius": "0.88",
        "kPlayerPercentFlat": btw("0.9"),
        "kPlayerLandChaos": "0.8",
        "kPlayerLandClumps": 2,
        "kPlayerFlatChaos": "0.8",
        "kPlayerFlatClumps": 1,
        "kPlayerTreePercentage": "0.25",
        "kTileDistanceBetweenPlayers": pick([20.0, 17.0, 15.0, 5.0, 5.0, 5.0, 5.0], n),
        "kNeutralInnerRadius": "0.05",
        "kNeutralOuterRadius": "0.05" if two else "0.35",
        "kNumInnerNeutrals": btw(0) if two else btw(2),
        "kInnerNeutralPercentLand": "0.2" if two else "0.02",
        "kInnerNeutralPercentFlat": btw("0.75"),
        "kInnerNeutralTreePercentage": "0.2",
        "kInnerNeutralLandChaos": "0.8",
        "kInnerNeutralLandClumps": btw(1),
        "kInnerNeutralFlatChaos": "0.8",
        "kInnerNeutralFlatClumps": 1,
        "kNumOuterNeutrals": btw(0),
        "kOuterNeutralPercentLand": "0.22",
        "kOuterNeutralPercentFlat": btw("0.5", "0.8"),
        "kOuterNeutralTreePercentage": "0.1",
        "kOuterNeutralLandChaos": "0.8",
        "kOuterNeutralLandClumps": 1,
        "kOuterNeutralFlatChaos": "0.8",
        "kOuterNeutralFlatClumps": 1,
        "kMaxResourceElevation": 2,
        "kResourceToEdgeDistance": 1,
        "kResourceToWaterDistance": 2,
        "kAnimalPerPlayer": 0,
        "kAnimalPerNeutral": 0,
        "kBerryPerNeutral": 0,
        "kFishPerPlayer": pick([16, 14, 14, 12, 12, 11, 10], n),
        "kFishPerNeutral": 0,
        "kGoldPerPlayer": gold,
        "kGoldPerNeutral": 0 if two else 2,
        "kStonePerPlayer": 2,
        "kStonePerNeutral": 0 if two else 1,
        "kTreePerPlayer": 1,
        "kTreePerNeutral": 0,
        "kForestFreeRadius": "7.0",
        "kForestsPerPlayer": forests,
        "kForestChaosLevel": "0.1",
        "kMaxClumpsPerForest": 3,
        "kForestToForestDistance": 5,
        "kForestOuterRadiusMultiplier": 6,
    }
    return d


def twin_rivers_n(n):
    return ["ResourceSeperation 7"]


def twin_rivers_s(s):
    lines = [
        "ResourcePlacementLimit (Berry, 5, 7)",
        "ResourcePlacementLimit (Fish, 1, %d)" % [60, 75, 100, 125, 170][s],
        "ResourcePlacementLimit (Tree, 4, 10)",
        "ResourcePlacementLimit (Animal, 8, 12)",
        "PlaceResourceInRing (Gold, 6, 8, 20)",
    ]
    if s <= 2:
        lines.append("ResourcePlacementLimit (Stone, 10, 14)")
    else:
        lines.append("PlaceResourceInRing (Stone, 10, 14, 20)")
    if s == 4:
        lines.append("ResourcePlacementLimit (Gold, 16, 100)")
        lines.append("ResourcePlacementLimit (Stone, 20, 100)")
    return lines


# --------------------------------------------------------------------------
# Uplands
# --------------------------------------------------------------------------
def uplands(n, s):
    n_in = max(0, [1, 2, 3, 6, 8][s] - (1 if n >= 7 else 0))
    n_out = [2, 6, 9, 16, 22][s] - ((n - 2) * [0, 0, 1, 1, 2][s]) // 2
    d = {
        "kMaxIntElevation": [10, 12, 15, 15, 15][s],
        "kElevationScale": btw(1),
        "kHeightMapChaos": [btw(12, 18), btw(20, 25), btw(30, 35), btw(25, 35), btw(25, 35)][s],
        "kMinimumStartPositionToMapEdge": 5,
        "kOuterPushFromMapCenter": 20,
        "kInnerPushFromMapCenter": 0,
        "kMaxAngleBetweenTeamMembers": pick([45.0, 45.0, 45.0, 45.0, 40.0, 40.0, 40.0], n),
        "kPlayerInnerRadius": "0.7",
        "kPlayerOuterRadius": "0.85",
        "kPlayerPercentFlat": btw("0.95"),
        "kPlayerLandChaos": "0.8",
        "kPlayerLandClumps": btw(1),
        "kPlayerFlatChaos": "0.8",
        "kPlayerFlatClumps": btw(1),
        "kPlayerTreePercentage": "0.09",
        "kTileDistanceBetweenPlayers": pick([20.0, 17.0, 15.0, 5.0, 5.0, 5.0, 5.0], n),
        "kNeutralInnerRadius": "0.3",
        "kNeutralOuterRadius": "0.4",
        "kNumInnerNeutrals": btw(n_in),
        "kInnerNeutralPercentLand": "0.2",
        "kInnerNeutralPercentFlat": btw("0.85"),
        "kInnerNeutralTreePercentage": "0.13",
        "kInnerNeutralLandChaos": "0.8",
        "kInnerNeutralLandClumps": btw(2),
        "kInnerNeutralFlatChaos": "0.8",
        "kInnerNeutralFlatClumps": btw(2),
        "kNumOuterNeutrals": btw(n_out),
        "kOuterNeutralPercentLand": "0.55",
        "kOuterNeutralPercentFlat": btw("0.85"),
        "kOuterNeutralTreePercentage": "0.16",
        "kOuterNeutralLandChaos": "0.8",
        "kOuterNeutralLandClumps": btw(2),
        "kOuterNeutralFlatChaos": "0.8",
        "kOuterNeutralFlatClumps": btw(2),
        "kMaxResourceElevation": 3,
        "kResourceToEdgeDistance": 2,
        "kResourceToWaterDistance": 4,
        "kAnimalPerPlayer": 0,
        "kAnimalPerNeutral": 0,
        "kFishPerPlayer": 0,
        "kFishPerNeutral": 0,
        "kGoldPerPlayer": 3,
        "kGoldPerNeutral": [8, 12, 18, 22, 24][s],
        "kStonePerPlayer": 2,
        "kStonePerNeutral": [2, 3, 4, 5, 6][s],
        "kTreePerPlayer": 1,
        "kTreePerNeutral": 0,
        "kForestFreeRadius": "8.0",
        "kForestsPerPlayer": 3,
        "kForestChaosLevel": "0.01",
        "kMaxClumpsPerForest": 3,
    }
    return d


def uplands_n(n):
    return ["ResourceSeperation %d" % pick([7, 6, 5, 5, 4, 4, 4], n)]


def uplands_s(s):
    lines = [
        "ResourcePlacementLimit (Stone, 10, %d)" % [14, 14, 14, 15, 15][s],
        "ResourcePlacementLimit (Berry, %d, %d)" % ((6, 7) if s < 3 else (7, 12)),
        "ResourcePlacementLimit (Fish, 1, 50)",
        "ResourcePlacementLimit (Tree, 3, %d)" % [5, 6, 6, 6, 6][s],
        "ResourcePlacementLimit (Animal, 7, 15)",
    ]
    if s < 3:
        lines.append("ResourcePlacementLimit (Gold, 7, 9)")
    else:
        lines.append("ResourcePlacementLimit (Gold, 8, 15)")
    if s in (1, 2):
        lines.append("PlaceResourceInRing (Gold, 12, 16)")
    return lines


# --------------------------------------------------------------------------
# Emission
# --------------------------------------------------------------------------
INCLUDES = """\
#include "Common\\Map Climate"
#include "Common\\Common Conditions"
#include "Common\\Common Terrain Painting"
#include "Common\\Common Initial Units"
#include "Common\\Common Forests"
"""

ATTR_BLOCKS = {
    # name -> (attribute line template list)
}

# Attribute section: (keyword, constant).  A constant that is a plain literal
# (starts with a digit, '-', or is true/false) is written as is.
def attr(key, val):
    return "%-32s%s" % (key, val)


def top_common_elevation(map_id):
    if map_id == "uplands":
        return [
            attr("MinIntElevation", "0"),
            attr("MaxIntElevation", "kMaxIntElevation"),
            attr("InitialElevation", "1"),
            attr("FlatElevation", "1"),
            attr("ElevationScale", "kElevationScale"),
            attr("HeightMapChaos", "kHeightMapChaos"),
            attr("HeightMapSmoothness", "0"),
        ]
    return [
        attr("MinIntElevation", "kMinIntElevation"),
        attr("MaxIntElevation", "kMaxIntElevation"),
        attr("InitialElevation", "0"),
        attr("FlatElevation", "1"),
        attr("ElevationScale", "kElevationScale"),
        attr("HeightMapChaos", "kHeightMapChaos"),
    ]


def land_water(map_id):
    if map_id == "uplands":
        return [
            attr("PercentLand", "1.0"),
            attr("LandElevationThreshold", "0"),
            attr("WaterBorder", "0"),
            attr("RiverWidth", "0"),
            attr("TeamGrowth", "false"),
            attr("LandfillPercentage", "0.4"),
            "",
            attr("CoastalToDeeperWaterPercentage", "0.0"),
            attr("ShallowsElevation", "kShallowsElevation"),
            attr("ShallowsWidth", "kShallowsWidth"),
            attr("MaxShallowConnectionsPerPlayer", "kMaxShallowConnectionsPerPlayer"),
            attr("GenerateShallows", "kGenerateShallows"),
        ]
    lines = [
        attr("PercentLand", "kPercentLand"),
        attr("LandElevationThreshold", "0"),
        attr("WaterBorder", "kWaterBorder"),
        attr("RiverWidth", "kRiverWidth"),
        attr("TeamGrowth", "false"),
    ]
    if map_id == "twin rivers":
        lines += [
            "",
            attr("RiverLandFill", "true"),
            attr("PeninsulaKiller", "kPeninsulaKiller"),
            attr("RiverLandFillWidth", "kRiverLandFillWidth"),
        ]
    lines += [
        "",
        attr("CoastalToDeeperWaterPercentage", "kCoastToDeepWaterPercentage"),
        attr("ShallowsElevation", "kShallowsElevation"),
        attr("ShallowsWidth", "kShallowsWidth"),
        attr("MaxShallowConnectionsPerPlayer", "kMaxShallowConnectionsPerPlayer"),
    ]
    if map_id == "twin rivers":
        lines.append(attr("TileDistanceBetweenShallows", "kTileDistanceBetweenShallows"))
    lines.append(attr("GenerateShallows", "kGenerateShallows"))
    return lines


def player_attrs(map_id):
    lines = [
        attr("PlayerInnerRadius", "kPlayerInnerRadius"),
        attr("PlayerOuterRadius", "kPlayerOuterRadius"),
        attr("PlayerPercentFlat", "kPlayerPercentFlat"),
        attr("PlayerTreePercentage", "kPlayerTreePercentage"),
        attr("PlayerLandChaos", "kPlayerLandChaos"),
        attr("PlayerLandClumps", "kPlayerLandClumps"),
        attr("PlayerFlatChaos", "kPlayerFlatChaos"),
        attr("PlayerFlatClumps", "kPlayerFlatClumps"),
        attr("MaxAngleBetweenTeamMembers", "kMaxAngleBetweenTeamMembers"),
        attr("TileDistanceBetweenPlayers", "kTileDistanceBetweenPlayers"),
    ]
    if map_id == "archipelago":
        lines.append(attr("PeninsulaKiller", "kPeninsulaKiller"))
    return lines


NEUTRAL_AND_RESOURCES = """\
// general pushing attributes
MinimumStartPositionToMapEdge   kMinimumStartPositionToMapEdge
OuterPushFromMapCenter          kOuterPushFromMapCenter
InnerPushFromMapCenter          kInnerPushFromMapCenter

// general neutral attributes
NeutralInnerRadius              kNeutralInnerRadius
NeutralOuterRadius              kNeutralOuterRadius

// inner neutral attributes
NumInnerNeutrals                kNumInnerNeutrals
InnerNeutralPercentLand         kInnerNeutralPercentLand
InnerNeutralPercentFlat         kInnerNeutralPercentFlat
InnerNeutralTreePercentage      kInnerNeutralTreePercentage
InnerNeutralLandChaos           kInnerNeutralLandChaos
InnerNeutralLandClumps          kInnerNeutralLandClumps
InnerNeutralFlatChaos           kInnerNeutralFlatChaos
InnerNeutralFlatClumps          kInnerNeutralFlatClumps

// outer neutral attributes
NumOuterNeutrals                kNumOuterNeutrals
OuterNeutralPercentLand         kOuterNeutralPercentLand
OuterNeutralPercentFlat         kOuterNeutralPercentFlat
OuterNeutralTreePercentage      kOuterNeutralTreePercentage
OuterNeutralLandChaos           kOuterNeutralLandChaos
OuterNeutralLandClumps          kOuterNeutralLandClumps
OuterNeutralFlatChaos           kOuterNeutralFlatChaos
OuterNeutralFlatClumps          kOuterNeutralFlatClumps

// resource attributes
MaxResourceElevation            kMaxResourceElevation
ResourceToEdgeDistance          kResourceToEdgeDistance
ResourceToWaterDistance         kResourceToWaterDistance

ResourcePerPlayer               (Animal,    kAnimalPerPlayer)
ResourcePerNeutralLand          (Animal,    kAnimalPerNeutral)

ResourcePerPlayer               (Berry,     kBerryPerPlayer)
ResourcePerNeutralLand          (Berry,     kBerryPerNeutral)
"""

FISH = """\

ResourcePerPlayer               (Fish,      kFishPerPlayer)
ResourcePerNeutralLand          (Fish,      kFishPerNeutral)
"""

REST = """\

ResourcePerPlayer               (Gold,      kGoldPerPlayer)
ResourcePerNeutralLand          (Gold,      kGoldPerNeutral)

ResourcePerPlayer               (Stone,     kStonePerPlayer)
ResourcePerNeutralLand          (Stone,     kStonePerNeutral)

ResourcePerPlayer               (Tree,      kTreePerPlayer)
ResourcePerNeutralLand          (Tree,      kTreePerNeutral)

// forest attributes
ForestFreeRadius                kForestFreeRadius
ForestsPerPlayer                kForestsPerPlayer
ForestChaosLevel                kForestChaosLevel
MaxClumpsPerForest              kMaxClumpsPerForest
"""


def forest_tail(map_id):
    if map_id == "twin rivers":
        return """\
ForestToForestDistance          kForestToForestDistance
MaximumTreesPerClump            kMaximumTreesPerClump
MaxTreeLoopCount                1000
ForestOuterRadiusMultiplier     kForestOuterRadiusMultiplier
TreeToEdgeDistance              0
"""
    return """\
MaximumTreesPerClump            10000
MaxTreeLoopCount                200
TreeToEdgeDistance              0
"""


def misc_tail(map_id):
    if map_id == "uplands":
        return """\

// misc. attributes
ConvergentSampleSize            32
ConvergentThreshold             1.0
MaxIterationsClumpGrowth        200
MaxLoopCount                    200
MapCharacteristics              WaterlessMap

// debug flags
FilterHeightMap                 false
TestingLandDistribution         false
"""
    return """\

// misc. attributes
ConvergentSampleSize            32
ConvergentThreshold             1.0
MaxIterationsClumpGrowth        200
MaxLoopCount                    200
MapCharacteristics              IslandMap

// debug flags
FilterHeightMap                 false
TestingLandDistribution         false
"""


MAPS = {
    "archipelago": dict(
        title="Archipelago",
        desc=["Many small islands for 2-8 players, naval focus.",
              "Each player starts on an island with its own gold, stone, forests and fish;",
              "extra islands hold more gold and stone."],
        ids=(27009, 26901),   # IDs of the slot it replaces (Caspian Sea); unused for display
        fn=archipelago, fn_n=archipelago_n, fn_s=archipelago_s,
        prelude=["#define\t\t(kShallowsElevation, -1)",
                 "#define\t\t(kShallowsWidth, 4)",
                 "#define\t\t(kMaxShallowConnectionsPerPlayer, 1)",
                 "#define\t\t(kGenerateShallows, false)"],
        berry_paleo=(2, 2),
    ),
    "twin rivers": dict(
        title="Twin Rivers",
        desc=["Large land map for 2v2 / 4v4: rivers with fords separate the two sides.",
              "Many forests, generous gold ring near each start."],
        ids=(27011, 26902),   # Channels
        fn=twin_rivers, fn_n=twin_rivers_n, fn_s=twin_rivers_s,
        prelude=["#define\t\t(kMaximumTreesPerClump,\t100)"],
        berry_paleo=(2, 1),
    ),
    "uplands": dict(
        title="Uplands",
        desc=["Open hill country with plateaus and choke points, rich in resources,",
              "meant for long games.  No water."],
        ids=(27020, 26916),   # Peloponnese
        fn=uplands, fn_n=uplands_n, fn_s=uplands_s,
        prelude=["#define\t\t(kShallowsElevation, -1)",
                 "#define\t\t(kShallowsWidth, 4)",
                 "#define\t\t(kMaxShallowConnectionsPerPlayer, 1)",
                 "#define\t\t(kGenerateShallows, false)"],
        berry_paleo=None,
    ),
}


def fmt_define(k, v):
    return "#define\t\t(%s,\t%s)" % (k, v)


def emit(map_id):
    m = MAPS[map_id]
    out = []
    w = out.append
    w("//////////////////////////////////////////////////////////////////////")
    w("// %s.rmv  (Rise and Fall remaster, original script)" % map_id)
    w("//")
    for ln in m["desc"]:
        w("// " + ln)
    w("// Generated by tools/gen_rms.py - edit the generator, not this file.")
    w("//////////////////////////////////////////////////////////////////////")
    w("")
    w('UseMapGenerator\t\t"Default"')
    w("StringTableID\t\t%d" % m["ids"][0])
    w("StringHelpID\t\t%d" % m["ids"][1])
    w("")
    w(INCLUDES)
    for p in m["prelude"]:
        w(p)
    w("")
    # --- player-count chain ------------------------------------------------
    for idx, n in enumerate(PLAYERS):
        w(("#if " if idx == 0 else "#elif ") + "Is%dPlayers" % n)
        for ln in m["fn_n"](n):
            w(ln)
        per_size = [m["fn"](n, s) for s in range(5)]
        keys = list(per_size[0].keys())
        for k in per_size[1:]:
            assert list(k.keys()) == keys
        const = [k for k in keys if all(str(d[k]) == str(per_size[0][k]) for d in per_size)]
        varying = [k for k in keys if k not in const]
        w("")
        for k in const:
            w(fmt_define(k, per_size[0][k]))
        for s in range(5):
            w("#if Is%sMap" % SIZES[s])
            for ln in m["fn_s"](s):
                w(ln)
            for k in varying:
                w(fmt_define(k, per_size[s][k]))
            w("#endif")
        # berries (epoch dependent)
        if m["berry_paleo"] is not None:
            w("#if (IsPaleoEpoch)")
            w(fmt_define("kBerryPerPlayer", m["berry_paleo"][0]))
            w("#else")
            w(fmt_define("kBerryPerPlayer", m["berry_paleo"][1]))
            w("#endif")
        else:
            w("#if OR(IsPaleoEpoch, IsStoneEpoch)")
            w(fmt_define("kBerryPerPlayer", 1))
            w(fmt_define("kBerryPerNeutral", 6))
            w("#else")
            w(fmt_define("kBerryPerPlayer", 1))
            w(fmt_define("kBerryPerNeutral", 0))
            w("#endif")
        w("")
    w("#endif")
    w("")
    # --- attribute section -------------------------------------------------
    w("//////////////////////////////////////////////////////////////////////")
    w("// Attributes we set")
    w("//////////////////////////////////////////////////////////////////////")
    w("// map elevation attributes")
    out.extend(top_common_elevation(map_id))
    w("")
    w("// land/water attributes")
    out.extend(land_water(map_id))
    w("")
    w("// player attributes")
    out.extend(player_attrs(map_id))
    w("")
    w(NEUTRAL_AND_RESOURCES.rstrip("\n"))
    if map_id != "uplands":
        w(FISH.rstrip("\n"))
    w(REST.rstrip("\n"))
    w(forest_tail(map_id).rstrip("\n"))
    w(misc_tail(map_id).rstrip("\n"))
    w("")
    return "\n".join(out)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "rms")
    os.makedirs(outdir, exist_ok=True)
    for map_id in MAPS:
        text = emit(map_id).replace("\r\n", "\n").replace("\n", "\r\n")
        path = os.path.join(outdir, map_id + ".rmv")
        with open(path, "w", newline="", encoding="ascii") as f:
            f.write(text)
        print("wrote", os.path.normpath(path), len(text), "bytes")


if __name__ == "__main__":
    main()

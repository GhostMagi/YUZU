// His game page, the emulator side. cube_main.cpp owns the screen and
// the touches; cube_game.cpp owns Walnut-CGB, his ROM and his save.
#pragma once
#include <stdint.h>

// 160x144 shown at 1.5x, which is as big as the cube's 240 rows allow.
static const int GAME_W = 240, GAME_H = 216;

// What a finger is holding, one bit each -- Walnut-CGB's own joypad
// bits (cube_game.cpp asserts they agree).
static const uint8_t GAME_A = 0x01, GAME_B = 0x02, GAME_SELECT = 0x04,
                     GAME_START = 0x08, GAME_RIGHT = 0x10, GAME_LEFT = 0x20,
                     GAME_UP = 0x40, GAME_DOWN = 0x80;

bool game_present();                 // was a game baked into this build
const char* game_title();
// Ready the game, drawing into dst (GAME_W x GAME_H, byte-swapped 565):
// nullptr when it is ready, otherwise a sentence saying why not.
const char* game_begin(uint16_t* dst);
void game_frame(uint8_t held);       // one Game Boy frame, 1/60s of game
bool game_drew();                    // a whole picture landed since last asked
const char* game_fault();            // nullptr, or why the game stopped
void game_save_if_due(bool now);     // writes his save once it settles

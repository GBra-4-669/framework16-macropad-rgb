// Keymap for the panel-palette firmware: Framework's default keymap with the layer
// hooks removed (led_update_user, keyboard_post_init_user, enable_factory_mode).
// Those hooks name layers by number (_FN is 1, _NUMLOCK and _FACTORY are others)
// and are written for Framework's layout, but this module runs an EEPROM keymap
// whose layer 1 is tc1, so the hooks were clearing the layer the keymap had just
// selected: TO(1) set layer 1 and the numlock hook took it straight back to 0,
// which made tc1 behave like tc0. The EEPROM keymap supplies the layout; this file
// only has to leave it alone. See README.md, "The layer-hook collision".

// Copyright 2022 Framework Computer
// SPDX-License-Identifier: GPL-2.0-or-later

#include QMK_KEYBOARD_H
#include "factory.h"

const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
     /*
     *         ┌────┬────┬────┬────┐
     *  4 keys │Esc │Calc│ =  │ <- │
     *         ├────┼────┼────┼────┤
     *  4 keys │ Num│ /  │ *  │ -  │
     *         ├────┼────┼────┼────┤
     *  3 keys │ 7  │ 8  │ 9  │ +  │
     *         ├────┼────┼────┼────┤
     *  4 keys │ 4  │ 5  │ 6  │ +  │
     *         ├────┼────┼────┼────┤
     *  3 keys │ 1  │ 2  │ 3  │Entr│
     *         ├────┼────┼────┼────┤
     *  3 keys │ 0  │ 0  │ .  │Entr│
     *         └────┴────┴────┴────┴
     * 21 total
     */
    [_NUMLOCK] = LAYOUT(
        KC_ESC,  KC_CALC, KC_EQL,  KC_BSPC,
        KC_NUM,  KC_PSLS, KC_PAST, KC_PMNS,
        KC_P7,   KC_P8,   KC_P9,   KC_PPLS,
        KC_P4,   KC_P5,   KC_P6,   KC_PPLS,
        KC_P1,   KC_P2,   KC_P3,   KC_PENT,
        KC_P0,   KC_P0,   KC_PDOT, KC_PENT
    ),
     /*
     *         ┌───────┬───────┬───────┬───────┐
     *  4 keys │ RGB   │ RGB + │ RGB + │ RGB + │
     *         │Toggle │ Speed │ Hue   │ Sat   │
     *         ├───────┼───────┼───────┼───────┤
     *  4 keys │Numlock│ RGB - │ RGB - │ RGB - │
     *         │       │ Speed │ Hue   │ Sat   │
     *         ├───────┼───────┼───────┼───────┤
     *  4 keys │ Home  │   ↑   │ Page  │RGB Nxt│
     *         │       │       │ Up    │Effect │
     *         ├───────┼───────┼───────┼───────┤
     *  4 keys │  ←    │       │   →   │RGB Prv│
     *         │       │       │       │Effect │
     *         ├───────┼───────┼───────┼───────┤
     *  4 keys │ End   │  ↓    │ Page  │ BL    │
     *         │       │       │ Down  │ Step  │
     *         ├───────┼───────┼───────┼───────┤
     *  4 keys │ Insert│ Insert│ Delete│ BL    │
     *         │       │       │       │ Step  │
     *         └───────┴───────┴───────┴───────┘
     * 24 total
     */
    [_FN] = LAYOUT(
        RGB_TOG, RGB_SPI, RGB_HUI, RGB_SAI,
        _______, RGB_SPD, RGB_HUD, RGB_SAD,
        _______, _______, _______, RGB_MOD,
        _______, _______, _______, RGB_RMOD,
        _______, _______, _______, BL_STEP,
        _______, _______, _______, BL_STEP
    ),
     /* Alphabet
     *         ┌────┬────┬────┬────┐
     *  4 keys │ A  │ B  │ C  │ D  │
     *         ├────┼────┼────┼────┤
     *  4 keys │ E  │ F  │ G  │ H  │
     *         ├────┼────┼────┼────┤
     *  4 keys │ I  │ J  │ K  │ L  │
     *         ├────┼────┼────┼────┤
     *  4 keys │ M  │ N  │ O  │ P  │
     *         ├────┼────┼────┼────┤
     *  4 keys │ Q  │ R  │ S  │ T  │
     *         ├────┼────┼────┼────┤
     *  4 keys │ U  │ V  │ W  │ X  │
     *         └────┴────┴────┴────┘
     * 24 total
     */
    [_FACTORY] = LAYOUT(
        KC_A,    KC_B,    KC_C,    KC_D,
        KC_E,    KC_F,    KC_G,    KC_H,
        KC_I,    KC_J,    KC_K,    KC_L,
        KC_M,    KC_N,    KC_O,    KC_P,
        KC_Q,    KC_R,    KC_S,    KC_T,
        KC_U,    KC_V,    KC_W,    KC_X
    ),
};

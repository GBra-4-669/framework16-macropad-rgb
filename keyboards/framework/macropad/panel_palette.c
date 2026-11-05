// Copyright 2026 Giulio Bramanti
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Per-key colours for the Laptop 16 RGB Macropad, for the on-screen deck panel.
//
// Added to Framework's macropad keyboard to colour keys individually, which the
// shipped firmware cannot do.
//
// Why it has to be firmware. The panel draws the deck's keys on screen, and
// colouring the keypad the same way lets a person find a key by matching the
// cell on the screen to the colour under their finger. Over VIA that is
// impossible: the keyboard-specific custom channel (0) is not implemented on
// this firmware at all, and rgb_matrix channel 3 holds one colour for the whole
// matrix. `qmk_hid`, Framework's own tool, has the same ceiling: brightness,
// effect, effect speed, hue, saturation, no per-key.
//
// So the split is:
//
//   * the 15 keys the panel maps get their own colour, and the host sets them
//     over VIA's custom channel (0), so changing the palette is software and
//     never needs another flash;
//   * every other key, the top row of layer keys and the keys the panel does not
//     map, shows the active layer's colour at low brightness. Dim reads as "not
//     a panel key" whatever the hue, while the hue still says which layer you
//     are on, which is also what the panel reads to know.

#include QMK_KEYBOARD_H

#define PANEL_ROWS 4
#define PANEL_COLS 4
#define PANEL_CELLS (PANEL_ROWS * PANEL_COLS)
#define PANEL_NONE 0xFF

// Brightness of the layer colour on keys that are not panel keys. Dim enough to
// read as "not clickable", bright enough to see which layer you are on.
#define PANEL_DIM 30

// One colour per layer; the top row selects layers 0-3. A cool-to-warm ramp, so
// the layer order reads off the keypad itself: tc0 is the coolest.
#define PANEL_LAYERS 4
#define LAYER_SAT 255
static const uint8_t layer_hue[PANEL_LAYERS] = {128, 85, 42, 0};

// Panel cell (col,row) -> LED index, or PANEL_NONE where the panel has no key.
// Physical row 0 is the layer row, so panel row r is the keypad's row r+1. Read
// out of g_led_config in macropad.c, which is the authoritative table, rather
// than from a drawing of the keypad.
static const uint8_t panel_led[PANEL_ROWS][PANEL_COLS] = {
    {4, 0, 20, 18},
    {7, 1, 21, 16},
    {6, 3, 23, 19},
    {9, 11, 15, PANEL_NONE},
};

// Default colours, replaced wholesale when the host pushes its palette. The host
// does that at startup, so these are only what the keypad shows until then (at
// the login screen, say), and never what the panel matches against.
//
// The 15 painted cells get hues spaced evenly over the 256-step wheel, then
// shuffled so keys that share an edge are at least 35 hue units apart. Cell 15,
// which the panel never uses, repeats cell 0's red.
//
// Written out as RGB rather than computed from hues at boot because every init
// hook this keyboard has is already taken: Framework's shared framework.c
// defines keyboard_post_init_kb, and macropad.c has the _user one.
static uint8_t panel_rgb[PANEL_ROWS][PANEL_COLS][3] = {
    {{255, 0, 0}, {0, 0, 255}, {0, 255, 0}, {204, 0, 255}},        // row 0
    {{0, 102, 255}, {204, 255, 0}, {102, 0, 255}, {102, 255, 0}},  // row 1
    {{255, 102, 0}, {0, 204, 255}, {255, 204, 0}, {255, 0, 204}},  // row 2
    {{0, 255, 204}, {255, 0, 102}, {0, 255, 102}, {255, 0, 0}},    // row 3
};

// Read-only diagnostics on the same channel, so the host can ask the module what
// it thinks instead of inferring it from a colour: value_id PANEL_QUERY_LAYER
// answers {layer it is on now, layers it has been on since boot, layer state
// low byte}. The colour is only an *indirect* signal, because it is set from the
// same layer state, and when a layer change did not show up in the colour there
// was no way to tell whether the keypad had not changed layer or this file had
// not noticed. This makes that answerable.
#define PANEL_QUERY_LAYER 0xF0
#define PANEL_QUERY_STATE 0xF1

static uint8_t panel_layer_changes = 0;   // times a layer hook has run

static uint8_t panel_layer_of(layer_state_t state) {
    for (int8_t l = 31; l > 0; l--) {
        if (state & ((layer_state_t)1u << l)) {
            return (uint8_t)l;
        }
    }
    return 0;
}

// Which layer is in force, asking both places QMK keeps one. A keymap can move
// layer_state (TO/MO/TG and friends) or the default layer (DF), and a layer is
// in force if either says so. Getting this wrong shows up immediately: the palette
// showed on every layer because only layer_state was consulted, and this
// keyboard's layer keys were not moving it.
static uint8_t panel_active_layer(void) {
    uint8_t momentary = panel_layer_of(layer_state);
    uint8_t base      = panel_layer_of(default_layer_state);
    return momentary > base ? momentary : base;
}

// Highest of two layer numbers, since "which layer is in force" is the highest
// that either mechanism has turned on.
static uint8_t panel_higher(uint8_t a, uint8_t b) { return a > b ? a : b; }

static void panel_apply_colour(uint8_t layer) {
    rgb_matrix_sethsv_noeeprom(layer_hue[layer % PANEL_LAYERS], LAYER_SAT, 255);
}

// This colour is what the module reports over VIA, and the panel reads it to
// know which layer is active, so it is set on every layer change rather than
// left to whatever happened to be in the EEPROM. Both hooks are implemented
// because either mechanism can move the layer, and the colour has to follow
// whichever one the keymap uses.
layer_state_t layer_state_set_kb(layer_state_t state) {
    panel_layer_changes++;
    panel_apply_colour(panel_higher(panel_layer_of(state), panel_layer_of(default_layer_state)));
    return state;
}

layer_state_t default_layer_state_set_kb(layer_state_t state) {
    panel_layer_changes++;
    panel_apply_colour(panel_higher(panel_layer_of(layer_state), panel_layer_of(state)));
    return state;
}

bool rgb_matrix_indicators_advanced_kb(uint8_t led_min, uint8_t led_max) {
    // Layer 0 is the panel's layer, and the only one this file has anything to
    // say about. Every other layer is left completely alone: the effect paints
    // the matrix in the layer's colour as it did before this file
    // existed. Colouring those layers too was the first thing the panel's owner
    // noticed was wrong: the palette belongs to the panel, and the panel is not
    // up on those layers.
    if (panel_active_layer() != 0) {
        return false;
    }

    RGB dim = hsv_to_rgb((HSV){.h = layer_hue[0], .s = LAYER_SAT, .v = (uint8_t)(255 * PANEL_DIM / 100)});

    // Everything starts as the layer colour, dimmed: that is what a key that is
    // not on the panel looks like.
    for (uint8_t i = led_min; i < led_max; i++) {
        rgb_matrix_set_color(i, dim.r, dim.g, dim.b);
    }

    // The panel's own keys, at full brightness.
    for (uint8_t r = 0; r < PANEL_ROWS; r++) {
        for (uint8_t c = 0; c < PANEL_COLS; c++) {
            uint8_t led = panel_led[r][c];
            if (led == PANEL_NONE || led < led_min || led >= led_max) {
                continue;
            }
            rgb_matrix_set_color(led, panel_rgb[r][c][0], panel_rgb[r][c][1], panel_rgb[r][c][2]);
        }
    }
    return false;
}

// VIA custom channel 0, which this firmware did not implement before: value_id is
// the panel cell (row * PANEL_COLS + col) and the data is its colour. The panel is
// the only writer, and it paints its own cells from the same table it pushes here,
// so the two cannot drift apart.
void via_custom_value_command_kb(uint8_t *data, uint8_t length) {
    uint8_t *command_id = &(data[0]);
    uint8_t *channel_id = &(data[1]);
    uint8_t *value_id   = &(data[2]);
    uint8_t *value_data = &(data[3]);

    if (*channel_id != id_custom_channel) {
        *command_id = id_unhandled;
        return;
    }

    // Read-only answers, so a layer that does not show up in the colour can be
    // told apart from a keypad that never changed layer.
    if (*value_id == PANEL_QUERY_LAYER || *value_id == PANEL_QUERY_STATE) {
        if (*command_id != id_custom_get_value) {
            *command_id = id_unhandled;
            return;
        }
        value_data[0] = panel_active_layer();
        value_data[1] = panel_layer_changes;
        value_data[2] = (uint8_t)((*value_id == PANEL_QUERY_LAYER ? layer_state : default_layer_state) & 0xFF);
        return;
    }

    if (*value_id >= PANEL_CELLS) {
        *command_id = id_unhandled;
        return;
    }

    uint8_t r = *value_id / PANEL_COLS;
    uint8_t c = *value_id % PANEL_COLS;

    switch (*command_id) {
        case id_custom_set_value:
            panel_rgb[r][c][0] = value_data[0];
            panel_rgb[r][c][1] = value_data[1];
            panel_rgb[r][c][2] = value_data[2];
            break;
        case id_custom_get_value:
            value_data[0] = panel_rgb[r][c][0];
            value_data[1] = panel_rgb[r][c][1];
            value_data[2] = panel_rgb[r][c][2];
            break;
        case id_custom_save:
            // Nothing to do: the palette belongs to the host. Persisting a
            // copy here would let the keypad and the panel disagree the moment
            // the host changed its mind while the keypad was unplugged.
            break;
        default:
            *command_id = id_unhandled;
            break;
    }
}

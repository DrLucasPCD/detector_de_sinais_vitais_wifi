#pragma once

#include <stdint.h>

#define RF_RAW_CSI_MAGIC 0xC5110001u
#define RF_MAX_SUBCARRIERS 512u
#define RF_MAX_WIRE_BYTES (20u + RF_MAX_SUBCARRIERS * 2u)

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint8_t node_id;
    uint8_t n_antennas;
    uint16_t n_subcarriers;
    uint32_t frequency_mhz;
    uint32_t sequence;
    int8_t rssi_dbm;
    int8_t noise_floor_dbm;
    uint16_t flags;
} rf_wire_header_t;

_Static_assert(sizeof(rf_wire_header_t) == 20, "wire v1 exige cabeçalho de 20 bytes");


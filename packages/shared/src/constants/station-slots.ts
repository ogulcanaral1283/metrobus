// Station Stop Positions — Overpass API'den
// Generated: 2026-03-05T07:28:31.435Z
// 42 durak, 77 stop_position

export interface StopPosition {
    id: number;
    lat: number;
    lon: number;
}

export interface StationSlotInfo {
    /** Durak adı */
    name: string;
    /** Bu duraktaki stop_position noktaları */
    stopPositions: StopPosition[];
    /** Slot sayısı (kaç otobüs aynı anda durabilir) */
    slotCount: number;
    /** Platform uzunluğu (metre) — en uzak iki slot arası */
    platformLengthMeters: number;
}

export const STATION_SLOTS: StationSlotInfo[] = [
  {
    "name": "Güzelyurt",
    "stopPositions": [
      {
        "id": 11663761160,
        "lat": 41.0065416,
        "lon": 28.6650232
      },
      {
        "id": 12772322403,
        "lat": 41.0064291,
        "lon": 28.6659231
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 77
  },
  {
    "name": "Beylikdüzü",
    "stopPositions": [
      {
        "id": 11663761159,
        "lat": 41.0098568,
        "lon": 28.6561403
      },
      {
        "id": 3739180659,
        "lat": 41.0096127,
        "lon": 28.6570764
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 83
  },
  {
    "name": "Haramidere",
    "stopPositions": [
      {
        "id": 11663761161,
        "lat": 41.005891,
        "lon": 28.6726999
      },
      {
        "id": 12772322404,
        "lat": 41.0059678,
        "lon": 28.6732793
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 49
  },
  {
    "name": "Avcılar Merkez-Üniversite Kampüsü",
    "stopPositions": [
      {
        "id": 4974306276,
        "lat": 40.9834238,
        "lon": 28.7260748
      },
      {
        "id": 2279591969,
        "lat": 40.9832492,
        "lon": 28.7266736
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 54
  },
  {
    "name": "Saadetdere Mahallesi",
    "stopPositions": [
      {
        "id": 12772322406,
        "lat": 40.9997945,
        "lon": 28.6921368
      },
      {
        "id": 12772322405,
        "lat": 40.9997701,
        "lon": 28.6930006
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 73
  },
  {
    "name": "Haramidere Sanayi",
    "stopPositions": [
      {
        "id": 11663761162,
        "lat": 41.0046939,
        "lon": 28.684335
      },
      {
        "id": 11663774831,
        "lat": 41.0043869,
        "lon": 28.6851377
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 76
  },
  {
    "name": "Beykent",
    "stopPositions": [
      {
        "id": 1832196141,
        "lat": 41.0195361,
        "lon": 28.6307252
      },
      {
        "id": 2365906983,
        "lat": 41.0194389,
        "lon": 28.6311682
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 39
  },
  {
    "name": "Şükrübey",
    "stopPositions": [
      {
        "id": 11663761167,
        "lat": 40.980113,
        "lon": 28.7317193
      },
      {
        "id": 11663774826,
        "lat": 40.9796187,
        "lon": 28.7327341
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 101
  },
  {
    "name": "Büyükşehir Belediyesi Sosyal Tesisleri",
    "stopPositions": [
      {
        "id": 2365232364,
        "lat": 40.9777941,
        "lon": 28.744498
      },
      {
        "id": 11663774825,
        "lat": 40.9780868,
        "lon": 28.7451939
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 67
  },
  {
    "name": "Cennet Mahallesi",
    "stopPositions": [
      {
        "id": 9164537141,
        "lat": 40.985292,
        "lon": 28.7826843
      },
      {
        "id": 9164537140,
        "lat": 40.9854181,
        "lon": 28.7831768
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 44
  },
  {
    "name": "Yenibosna",
    "stopPositions": [
      {
        "id": 12773099559,
        "lat": 40.9925023,
        "lon": 28.8316149
      },
      {
        "id": 2366851849,
        "lat": 40.9924576,
        "lon": 28.833693
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 174
  },
  {
    "name": "Şirinevler",
    "stopPositions": [
      {
        "id": 11663787474,
        "lat": 40.9916955,
        "lon": 28.8457211
      },
      {
        "id": 12773099561,
        "lat": 40.9917268,
        "lon": 28.8468846
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 98
  },
  {
    "name": "Bahçelievler",
    "stopPositions": [
      {
        "id": 11663787475,
        "lat": 40.9949189,
        "lon": 28.8631591
      },
      {
        "id": 11663774817,
        "lat": 40.9952169,
        "lon": 28.8639067
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 71
  },
  {
    "name": "İncirli",
    "stopPositions": [
      {
        "id": 2366832557,
        "lat": 40.9980934,
        "lon": 28.8734765
      },
      {
        "id": 11716357231,
        "lat": 40.9984283,
        "lon": 28.8744136
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 87
  },
  {
    "name": "Zeytinburnu",
    "stopPositions": [
      {
        "id": 7810984116,
        "lat": 41.0032266,
        "lon": 28.89062
      },
      {
        "id": 7810984107,
        "lat": 41.0036949,
        "lon": 28.8913808
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 82
  },
  {
    "name": "Merter",
    "stopPositions": [
      {
        "id": 11663787478,
        "lat": 41.0075579,
        "lon": 28.8973383
      },
      {
        "id": 11663774814,
        "lat": 41.0080164,
        "lon": 28.8978876
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 69
  },
  {
    "name": "Cevizlibağ",
    "stopPositions": [
      {
        "id": 11663787479,
        "lat": 41.0165595,
        "lon": 28.9111949
      },
      {
        "id": 2361777023,
        "lat": 41.016979,
        "lon": 28.9117377
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 65
  },
  {
    "name": "Topkapı - Şehit Mustafa Cambaz",
    "stopPositions": [
      {
        "id": 4974583284,
        "lat": 41.0202697,
        "lon": 28.9171833
      },
      {
        "id": 4974583283,
        "lat": 41.0202205,
        "lon": 28.9172415
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 7
  },
  {
    "name": "Bayrampaşa - Maltepe / Koç Üniversitesi Hastanesi",
    "stopPositions": [
      {
        "id": 1868232089,
        "lat": 41.0235335,
        "lon": 28.921197
      },
      {
        "id": 2366822776,
        "lat": 41.024095,
        "lon": 28.9215528
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 69
  },
  {
    "name": "Edirnekapı",
    "stopPositions": [
      {
        "id": 6934423349,
        "lat": 41.0331979,
        "lon": 28.9292344
      },
      {
        "id": 12773099569,
        "lat": 41.0337289,
        "lon": 28.929965
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 85
  },
  {
    "name": "Ayvansaray Eyüpsultan",
    "stopPositions": [
      {
        "id": 12773099571,
        "lat": 41.0387969,
        "lon": 28.937756
      },
      {
        "id": 12773099570,
        "lat": 41.0395577,
        "lon": 28.9384376
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 102
  },
  {
    "name": "Söğütlüçeşme",
    "stopPositions": [
      {
        "id": 1732274346,
        "lat": 40.9916216,
        "lon": 29.0377008
      },
      {
        "id": 1732274373,
        "lat": 40.9920083,
        "lon": 29.0378226
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 44
  },
  {
    "name": "Fikirtepe",
    "stopPositions": [
      {
        "id": 12773099592,
        "lat": 40.9936123,
        "lon": 29.0470126
      },
      {
        "id": 12773099591,
        "lat": 40.9938082,
        "lon": 29.0475885
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 53
  },
  {
    "name": "Uzunçayır",
    "stopPositions": [
      {
        "id": 4974583281,
        "lat": 40.9986206,
        "lon": 29.056334
      },
      {
        "id": 1755163855,
        "lat": 40.9990338,
        "lon": 29.0566706
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 54
  },
  {
    "name": "Acıbadem",
    "stopPositions": [
      {
        "id": 12773099587,
        "lat": 41.0148724,
        "lon": 29.0567804
      },
      {
        "id": 12773099588,
        "lat": 41.0144005,
        "lon": 29.0575861
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 86
  },
  {
    "name": "Halıcıoğlu",
    "stopPositions": [
      {
        "id": 2363259651,
        "lat": 41.0485647,
        "lon": 28.9461655
      },
      {
        "id": 12773099572,
        "lat": 41.0491205,
        "lon": 28.9466187
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 73
  },
  {
    "name": "Okmeydanı",
    "stopPositions": [
      {
        "id": 12773099573,
        "lat": 41.0562446,
        "lon": 28.9608751
      },
      {
        "id": 12773099574,
        "lat": 41.0566936,
        "lon": 28.9614207
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 68
  },
  {
    "name": "Darülaceze - Perpa",
    "stopPositions": [
      {
        "id": 12773099576,
        "lat": 41.061901,
        "lon": 28.9674171
      },
      {
        "id": 12773099575,
        "lat": 41.0623327,
        "lon": 28.9676634
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 52
  },
  {
    "name": "Okmeydanı Hastane Metrobüs durağı",
    "stopPositions": [
      {
        "id": 12773099578,
        "lat": 41.0673763,
        "lon": 28.9760168
      },
      {
        "id": 12773099579,
        "lat": 41.0674685,
        "lon": 28.9765993
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 50
  },
  {
    "name": "Çağlayan",
    "stopPositions": [
      {
        "id": 12773099580,
        "lat": 41.0673265,
        "lon": 28.9805785
      },
      {
        "id": 12773099581,
        "lat": 41.0673726,
        "lon": 28.9815307
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 80
  },
  {
    "name": "Mecidiyeköy",
    "stopPositions": [
      {
        "id": 2363270655,
        "lat": 41.0668482,
        "lon": 28.9912386
      },
      {
        "id": 11663774803,
        "lat": 41.0669107,
        "lon": 28.9918981
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 56
  },
  {
    "name": "15 Temmuz Şehitler Köprüsü",
    "stopPositions": [
      {
        "id": 12801220432,
        "lat": 41.0351033,
        "lon": 29.0437178
      },
      {
        "id": 7798705638,
        "lat": 41.0368124,
        "lon": 29.0435397
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 191
  },
  {
    "name": "Zincirlikuyu",
    "stopPositions": [
      {
        "id": 12328413560,
        "lat": 41.0659364,
        "lon": 29.0129203
      },
      {
        "id": 12328413561,
        "lat": 41.0664044,
        "lon": 29.0130926
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 54
  },
  {
    "name": "Altunizade",
    "stopPositions": [
      {
        "id": 12773099586,
        "lat": 41.0212803,
        "lon": 29.0489017
      },
      {
        "id": 12773099585,
        "lat": 41.0220861,
        "lon": 29.0481789
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 108
  },
  {
    "name": "Burhaniye",
    "stopPositions": [
      {
        "id": 12773099584,
        "lat": 41.03199,
        "lon": 29.0469814
      },
      {
        "id": 12592858808,
        "lat": 41.032303,
        "lon": 29.0470902
      }
    ],
    "slotCount": 2,
    "platformLengthMeters": 36
  },
  {
    "name": "Cumhuriyet Mahallesi",
    "stopPositions": [
      {
        "id": 11663761157,
        "lat": 41.0154421,
        "lon": 28.6413758
      }
    ],
    "slotCount": 1,
    "platformLengthMeters": 0
  },
  {
    "name": "Beylikdüzü Belediye",
    "stopPositions": [
      {
        "id": 12772322402,
        "lat": 41.0126099,
        "lon": 28.6488069
      }
    ],
    "slotCount": 1,
    "platformLengthMeters": 0
  },
  {
    "name": "Mustafa Kemalpaşa",
    "stopPositions": [
      {
        "id": 11663761164,
        "lat": 40.9950109,
        "lon": 28.7060398
      }
    ],
    "slotCount": 1,
    "platformLengthMeters": 0
  },
  {
    "name": "Küçükçekmece",
    "stopPositions": [
      {
        "id": 1867720187,
        "lat": 40.9863704,
        "lon": 28.7696721
      }
    ],
    "slotCount": 1,
    "platformLengthMeters": 0
  },
  {
    "name": "Florya",
    "stopPositions": [
      {
        "id": 11663787470,
        "lat": 40.9865232,
        "lon": 28.7881632
      }
    ],
    "slotCount": 1,
    "platformLengthMeters": 0
  },
  {
    "name": "Beşyol",
    "stopPositions": [
      {
        "id": 11663787471,
        "lat": 40.9940111,
        "lon": 28.7948098
      }
    ],
    "slotCount": 1,
    "platformLengthMeters": 0
  },
  {
    "name": "Sefaköy",
    "stopPositions": [
      {
        "id": 11663787472,
        "lat": 40.99818,
        "lon": 28.7979256
      }
    ],
    "slotCount": 1,
    "platformLengthMeters": 0
  }
];

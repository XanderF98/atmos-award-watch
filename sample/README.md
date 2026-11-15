# Sample dashboard (made-up data)

Checked 2026-11-15 19:07 UTC for 2 traveler(s). Award data from [seats.aero](https://seats.aero); it is cached, so confirm on alaskaair.com before acting.

## Can we book the whole trip?

| Option | Out | Back | Nights | Points for 2 | Taxes | Against 91,000 |
|---|---|---|---|---|---|---|
| Economy both ways | Oct 3 SEA-MXP (economy, 27,500, connecting) | Oct 12 FCO-SEA (economy, 30,000, nonstop) | 9 | 115,000 | $294 | 24,000 short |
| Business out, economy back | Oct 2 YVR-MXP (business, 45,000, connecting), via Vancouver | Oct 12 FCO-SEA (economy, 30,000, nonstop) | 10 | 150,000 | $378 | 59,000 short |
| Economy out, premium back | Oct 3 SEA-MXP (economy, 27,500, connecting) | Oct 12 FCO-SEA (premium, 50,000, nonstop) | 9 | 155,000 | $294 | 64,000 short |
| Economy out, business back | Oct 3 SEA-MXP (economy, 27,500, connecting) | Oct 13 DUB-SEA (business, 55,000, nonstop), via Dublin | 10 | 165,000 | $308 | 74,000 short |
| Business out, premium back | Oct 2 YVR-MXP (business, 45,000, connecting), via Vancouver | Oct 12 FCO-SEA (premium, 50,000, nonstop) | 10 | 190,000 | $378 | 99,000 short |
| Business both ways | Oct 2 YVR-MXP (business, 45,000, connecting), via Vancouver | Oct 13 DUB-SEA (business, 55,000, nonstop), via Dublin | 11 | 200,000 | $392 | 109,000 short |

![Cheapest round trip over time](chart.svg)

## Is it cheaper to land somewhere else in Europe?

**Seattle to Europe**

| Airport | Connection | Economy | Business | Worth the detour? |
|---|---|---|---|---|
| Milan Malpensa (MXP) | Already there | 27,500 | 70,000 |  |
| Dublin (DUB) | a 2.5 to 3 hour flight to or from Italy | 27,500 | 55,000 | economy same price; business saves 15,000 (yes) |

Nothing bookable yet at Rome (FCO), Milan Linate (LIN), London (LHR), Paris (CDG), Helsinki (HEL), Reykjavik (KEF).

**Europe to Seattle**

| Airport | Connection | Economy | Premium | Business | First | Worth the detour? |
|---|---|---|---|---|---|---|
| Rome (FCO) | Already there | 30,000 | 50,000 | 85,000 | - |  |
| Naples (NAP) | Already there | - | - | - | 90,000 |  |
| Dublin (DUB) | a 2.5 to 3 hour flight to or from Italy | 27,500 | - | 55,000 | - | economy saves 2,500; business saves 30,000 (yes) |

Nothing bookable yet at Milan Malpensa (MXP), London (LHR), Paris (CDG), Helsinki (HEL), Reykjavik (KEF).

Points are per person, one way, to or from Seattle, counting only flights with seats for everyone and taxes under the cap. A detour gets a yes only when it saves at least the amount set for it in the watchlist, because the hop to Italy is booked separately and costs time and cash.

## Which dates can be booked yet?

- **Seattle to Europe:** 12 of 16 dates can be booked (through Oct 12). Oct 13 opens Nov 16; all are open by Nov 19.
- **Europe to Seattle:** 3 of 19 dates can be booked (through Oct 12). Oct 13 opens Nov 16; all are open by Dec 1.

## Is the data source covering our routes?

- **Seattle to Europe:** data for SEA-MXP, SEA-LIN, SEA-DUB, SEA-LHR, YVR-MXP, PDX-MXP. Nothing returned for SEA-FCO, SEA-CDG, SEA-HEL, SEA-KEF, YVR-FCO, YVR-LIN, YVR-DUB, YVR-LHR, YVR-CDG, YVR-HEL, YVR-KEF, PDX-FCO, PDX-LIN, PDX-DUB, PDX-LHR, PDX-CDG, PDX-HEL, PDX-KEF.
- **Europe to Seattle:** data for FCO-SEA, NAP-SEA, DUB-SEA. Nothing returned for FCO-YVR, FCO-PDX, NAP-YVR, NAP-PDX, MXP-SEA, MXP-YVR, MXP-PDX, DUB-YVR, DUB-PDX, LHR-SEA, LHR-YVR, LHR-PDX, CDG-SEA, CDG-YVR, CDG-PDX, HEL-SEA, HEL-YVR, HEL-PDX, KEF-SEA, KEF-YVR, KEF-PDX.

A route with nothing returned is usually one seats.aero does not track, not one that is sold out.

## Cheapest one-way price by cabin

**Seattle to Europe** (5 deals meeting the rules)

| Cabin | Points each | On | Route | Days with space |
|---|---|---|---|---|
| Business | 45,000 | Oct 2 | YVR-MXP | 5 |
| Economy | 27,500 | Oct 2 | SEA-DUB | 2 |

**Europe to Seattle** (4 deals meeting the rules)

| Cabin | Points each | On | Route | Days with space |
|---|---|---|---|---|
| First | 90,000 | Oct 14 | NAP-SEA | 1 |
| Business | 55,000 | Oct 13 | DUB-SEA | 2 |
| Premium | 50,000 | Oct 12 | FCO-SEA | 1 |
| Economy | 27,500 | Oct 13 | DUB-SEA | 2 |


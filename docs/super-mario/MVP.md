# Super Mario (Web Canvas) - MVP Scope

## Cilj
Napraviti igrivu mini-platformer verziju (1 nivo) u browseru koristeci HTML Canvas, sa osnovnim loop/render/input/collision sistemom.

## Platforma / Tehnologija
- Render: `CanvasRenderingContext2D` (2D)
- Integracija: kao tab u postojecem Vite/React frontendu (`app/frontend`)
- Kontrole: tastatura (touch opcionalno kasnije)

## MVP Feature List
- Player (Mario)
  - Kretanje levo/desno
  - Skok + gravitacija
  - Osnovne animacije ili placeholder (dok ne dodamo sprites)
  - Kolizija sa zemljom i blokovima (tile collision)
- Level
  - 1 nivo (tile grid) sa:
    - podlogom
    - par platformi
    - death zona (pad)
    - cilj (flag/exit zona)
- Enemies
  - 1 tip: Goomba (patrolira)
  - Interakcija:
    - stomp odozgo => neprijatelj umire
    - kontakt sa strane => player "umire" (lose)
- Collectibles
  - coin pickup (brojac + score)
- UI/HUD
  - score, coins, time (simple timer), lives (moze 1 za MVP)
  - ekrani: win, gameover, restart

## Non-goals (za MVP)
- Više nivoa, world map
- Kompleksan physics (slopes), napredni power-up chain
- Kompletny art/audio set (mozemo krenuti placeholder)
- Save/load

## Acceptance Criteria
1. Otvaranjem taba "Mario" prikazuje se canvas i igra se moze startovati bez reload-a stranice.
2. Mario se krece i skace fluidno, uz stabilan game loop (bez "speed-up" na brzim masinama).
3. Mario ne prolazi kroz solid tile-ove; pravilno se zaustavlja na podlozi i platformama.
4. Coin pickup povecava brojac i score.
5. Goomba patrolira; stomp ga uklanja; kontakt sa strane zavrsava igru.
6. Win zona zavrsava nivo; prikazuje win ekran + restart.
7. Gameover ekran nudi restart na isti nivo.


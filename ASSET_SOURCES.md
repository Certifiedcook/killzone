# Third-party presentation assets

Kill Zone's code can download a small optional presentation pack into `assets/audio/` and `assets/fx/` on first launch. The game does not require these files to simulate combat.

All media listed here was selected because its source records it as **CC0 / public-domain-equivalent**. The source pages remain the authoritative licence records; this file documents what the project expects to download and why.

## Gunfire

Files:

- `rifle_556.mp3`
- `rifle_762.mp3`
- `smg_9mm.mp3`

Authors: Ben Jaszczak, Brian Nelson, Kevin Heras, Matthew Nanney  
Original collection: **The Free Firearm Sound Library** on OpenGameArt  
Licence: **CC0 1.0**

The small encoded versions used by the downloader are mirrored by the public `fatal-funnel-public` repository. Its asset licence register identifies these exact files as derived from The Free Firearm Sound Library, CC0-1.0, with redistribution allowed.

Source page:

`https://opengameart.org/content/the-free-firearm-sound-library`

Mirror used by the downloader:

`https://github.com/euuuuuuan/fatal-funnel-public`

## Explosions

Files:

- `explosion1.ogg`
- `explosion2.ogg`

Author: EZduzziteh  
Source: **Explosions** — OpenGameArt  
Licence: **CC0**

`https://opengameart.org/content/explosions-4`

## Hurt / pain vocalisations

Files:

- `hurt_01.mp3`
- `hurt_03.mp3`

Author: EZduzziteh  
Source: **Hurt Sound Effects** — OpenGameArt  
Licence: **CC0**

`https://opengameart.org/content/hurt-sound-effects`

## Death / pain vocalisation

File:

- `scream_horror1.mp3`

Author: Vinrax  
Source: **Horror scream1** — OpenGameArt  
Licence: **CC0**

`https://opengameart.org/content/horror-scream1`

This is intentionally played at low volume and mixed with shorter hurt sounds so fatalities do not produce a loud scream every time.

## Blood decal

File:

- `blood_red.png`

Author: AntumDeluge  
Source: **Blood Splatters** — OpenGameArt  
Licence: **CC0**

`https://opengameart.org/content/blood-splatters`

Kill Zone also has a procedural blood-decal fallback when this sprite is unavailable.

## Runtime behaviour

The asset URLs are declared in `ASSET_MANIFEST` inside `kill_zone.py`. Downloads occur in a daemon thread so a slow or offline network does not block the main menu. Existing local files are never re-downloaded.

The audio and blood assets are presentation only. They do not feed the AI, spotting system or any sound-detection gameplay system.

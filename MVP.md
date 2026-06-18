
# 1. Produktdefinition

## Name

**RouteSnap**

## Zweck

**RouteSnap** ist ein **reiner Renderer** für ÖPNV-Verbindungen.

Er macht **kein Routing**, **keine API-Calls**, **keine Station-Suche**.
Er nimmt bereits vorhandene Verbindungsdaten entgegen und rendert daraus ein **visuelles Share-/Preview-Bild**.

## Ziel

Aus Routing-Daten soll automatisch eine Grafik entstehen, die:

* mobil gut lesbar ist
* schnell erfassbar ist
* visuell hochwertig aussieht
* sich gut zum Teilen eignet

---

# 2. Scope

Wir bauen das Tool **komplett unabhängig** vom Datenscript.

## Das heißt konkret

### Bestehendes Tool

* `vbb.py` holt und normalisiert die Daten

### Neues Tool

* `routesnap` rendert daraus SVG/PNG

## Pipeline

```bash
python vbb.py journey ... --json > route.json
routesnap render route.json --out route.svg
```

Oder per Pipe:

```bash
python vbb.py journey ... --json | routesnap render --stdin --out route.svg
```

---

# 3. MVP-Definition

Der MVP von **RouteSnap** kann genau Folgendes:

## Eingabe

* JSON im Format deines `vbb.py --json`

## Ausgabe

* **SVG** als Primärformat
* optional **PNG**

## Darstellung

* **eine Hauptverbindung**
* plus **maximal eine Alternative**
* also insgesamt **höchstens 2 Routen**

## Layout

* **Wenn nur eine Route vorhanden ist:** vertikaler Graph
* **Wenn zwei Routen vorhanden sind:** gemeinsamer Stamm + **ein Split-Punkt** + zwei Äste bis zum Ziel

## Stil

* dunkler Hintergrund
* clean / minimalistisch
* Neon-Akzente
* Linear-artiger Look
* keine überladene Cyberpunk-Optik

---

# 4. Feste Layout-Regel

## Fall A: Eine Route

Darstellung als **vertikaler Pfad**:

```txt
Titel
26 min · 2 Umstiege · 6 min Fußweg
08:15 → 08:41

● Start
│
○ Alexanderplatz
│
⋮ Fußweg 2 min
│
○ Jannowitzbrücke
│
● Ziel
```

### Knotentypen

* **Start:** gefüllter Kreis
* **Umstieg:** leerer Kreis
* **Ziel:** gefüllter Kreis

### Segmenttypen

* **Transit:** durchgezogene Neon-Linie
* **Fußweg:** gepunktete / gestrichelte Linie

---

## Fall B: Zwei Routen

Darstellung als **ein Stamm mit genau einem Split**.

### Feste Regel

* Beide Routen starten gemeinsam am **Startknoten**
* Es wird der **gemeinsame Präfix** beider Routen gebildet
* Am ersten Punkt, an dem sie sich unterscheiden, entsteht der **Split-Knoten**
* Ab dort laufen **zwei getrennte Äste**
* Jeder Ast endet in einem **eigenen Zielknoten mit Zielzeit**

### Beispiel

```txt
Nach Hause
26 min · 1 Alternative
08:15 → 08:41 / 08:45

● Start 08:15
│
○ Alexanderplatz
│
├── Route A: S3
│   ○ Ostkreuz
│   ● Ziel 08:41
│
└── Route B: U5
    ○ Frankfurter Allee
    ● Ziel 08:45
```

## Wichtige feste Einschränkung

Im MVP gibt es:

* **maximal 2 Routen**
* **maximal 1 Split**
* **keine Re-Merges**

Das heißt: Wenn sich reale Routen später wieder vereinen, wird das **nicht** wieder zusammengeführt.
Nach dem Split bleiben die beiden Äste getrennt bis zum Ende.

Das ist absichtlich so, damit das Layout stabil und gut lesbar bleibt.

---

# 5. Feste Auswahlregel für Alternativen

Wenn `vbb.py` mehr als 2 Journeys liefert, rendert RouteSnap **nicht alle**, sondern nur:

1. **beste Route**
2. **zweitbeste Route**

## Ranking-Regel

Die Routen werden nach dieser Priorität sortiert:

1. **kürzeste Dauer**
2. **wenigste Umstiege**
3. **wenigster Fußweg**
4. **frühere Ankunft**

Danach werden nur die ersten zwei verwendet.

Damit ist die Darstellung immer kontrolliert und bleibt kompakt.

---

# 6. Feste Datenbasis

## RouteSnap erwartet als Input zunächst das bestehende JSON aus `vbb.py`

also mit:

* `origin`
* `destination`
* `realtimeDataUpdatedAt`
* `journeys[]`

und pro Journey:

* `departure`
* `arrival`
* `duration_min`
* `transfers`
* `cancelled`
* `remarks`
* `legs[]`

und pro Leg:

* `line`
* `direction`
* `origin`
* `destination`
* `departure`
* `arrival`
* `delay`
* `cancelled`
* `remarks`


---

# 7. Eine kleine Änderung am JSON

Wir führen **genau zwei zusätzliche Felder pro Leg** ein.

## Diese beiden Felder sind verpflichtend:

### 1. `type`

Werte:

* `"transit"`
* `"walk"`

### 2. `duration_min`

Dauer des Legs in Minuten

---

## Warum diese Änderung notwendig ist

Mit dem aktuellen kompakten JSON kann RouteSnap zwar viel erkennen, aber nicht robust genug:

* Fußwege werden derzeit indirekt über `line == "walk"` erkannt
* Leg-Dauer ist nicht sauber enthalten
* für die Darstellung von Fußweg-Segmenten ist `duration_min` wichtig

Darum ist die **verbindliche Anpassung** an `vbb.py`:

```json
{
  "line": "S3",
  "type": "transit",
  "direction": "Erkner",
  "origin": "Alexanderplatz",
  "destination": "Ostkreuz",
  "departure": "08:15",
  "arrival": "08:27",
  "duration_min": 12,
  "delay": "pünktlich",
  "cancelled": false,
  "remarks": []
}
```

und z. B. für einen Fußweg:

```json
{
  "line": "walk",
  "type": "walk",
  "origin": "Alexanderplatz",
  "destination": "U Alexanderplatz",
  "departure": "08:27",
  "arrival": "08:29",
  "duration_min": 2,
  "delay": "",
  "cancelled": false,
  "remarks": []
}
```


---

# 8. Feste interne Datenstruktur

Intern normalisiert RouteSnap die Daten in dieses Modell:

```ts
type Snapshot = {
  title: string
  originName: string
  destinationName: string
  generatedAt?: number
  options: RouteOption[]
}

type RouteOption = {
  id: string
  departure: string
  arrival: string
  durationMin: number
  transfers: number
  walkingMin: number
  cancelled: boolean
  remarks: string[]
  legs: Leg[]
}

type Leg = {
  type: "transit" | "walk"
  line: string
  direction?: string
  origin: string
  destination: string
  departure?: string
  arrival?: string
  durationMin: number
  delay?: string
  cancelled: boolean
  remarks: string[]
}
```

---

# 9. Rendering-Regeln

## Header

Ganz oben stehen immer:

* Titel - On Top
* Gesamtdauer
* Anzahl Umstiege
* gesamte Fußwegzeit
* Abfahrt → Ankunft

### Beispiel

```txt
Nach Hause
26 min · 2 Umstiege · 6 min Fußweg
08:15 → 08:41
```

---

## Knotenbeschriftung

Jeder Knoten zeigt:

* Haltestellenname
* optional Uhrzeit

### Beispiel

```txt
Alexanderplatz
08:27
```

---

## Segmentbeschriftung

Jedes Segment zeigt:

* Linie
* Richtung
* Dauer

### Beispiel

```txt
S3 · Richtung Ostkreuz
12 min
```

Für Fußweg:

```txt
Fußweg
2 min
```

---

## Statusanzeige

Wenn vorhanden, wird je Segment angezeigt:

* `+5 min`
* `pünktlich`
* `CANCELLED`

`cancelled == true` wird zusätzlich farblich markiert.

---

## Remarks

Remarks werden im MVP **nicht pro Segment groß aufgeblasen**, sondern nur unten kompakt gesammelt:

```txt
Hinweise
- Bauarbeiten auf Linie U8
- Verspätung wegen Signalstörung
```

Maximal **3 Hinweise**.

---

# 10. Feste Style-Definition

## Format

Standard-Canvas:

```txt
1080 × 1920 px
```

Hochformat, mobil optimiert, wenn wenig Infos dargestellt werden kann die Höhe entsprechend verringert / vergrößert werden. 

---

## Farben

### Hintergrund

* `#0B0D12`

### Surface / Card

* `#121722`

### Primärtext

* `#F3F6FB`

### Sekundärtext

* `#97A3B6`

### Linienfarben

* S-Bahn: Neon-Grün
* U-Bahn: Neon-Gelb
* Tram: Neon-Magenta
* Bus: Neon-Orange
* Fußweg: Hellgrau / Cyan gestrichelt

Wenn Verkehrsmittel nicht sicher erkannt wird:

* Fallback: Neon-Blau

---

## Linien

* 4 px
* runde Enden
* leichter Glow

## Glow

* dezent
* nicht übertrieben
* eher Linear als Tron

## Typografie

* modern, clean, sans-serif
* klare Hierarchie
* kein überladenes UI

---

# 11. Technische Umsetzung

## Sprache

**Python**

## Rendering

* SVG wird direkt als XML/String erzeugt
* PNG wird aus SVG exportiert

# 13. Feste CLI-Schnittstelle

## Rendern aus Datei

```bash
routesnap render route.json --out route.svg
```

## Rendern aus stdin

```bash
cat route.json | routesnap render --stdin --out route.svg
```

## PNG-Ausgabe

```bash
routesnap render route.json --out route.png
```

## Titel überschreiben

```bash
routesnap render route.json --out route.svg --title "Nach Hause"
```

---

# 15. Definition des Split-Algorithmus

Das ist wichtig, also ganz konkret:

## Eingabe

Zwei Journey-Optionen, jeweils als Leg-Liste.

## Vorgehen

1. Beide Leg-Listen werden in Sequenzen von Stationen/Knoten überführt
2. Der **längste gemeinsame Präfix** wird bestimmt
3. Der letzte gemeinsame Knoten ist der **Split-Knoten**
4. Bis zu diesem Split-Knoten wird **ein gemeinsamer Stamm** gezeichnet
5. Danach werden die beiden Restpfade als **linker und rechter Ast** gezeichnet
6. Es gibt **keine spätere Wiedervereinigung**

## Wenn kein gemeinsamer Präfix außer dem Start existiert

Dann erfolgt der Split direkt am Start.

## Wenn beide Routen identisch sind

Dann wird nur eine Route gezeichnet.

---

# 16. Definition der Zielgrafik

Die Standardgrafik sieht damit so aus:

## Oben

* Titel
* Kennzahlen

## Mitte

* gemeinsamer Stamm
* optional Split in zwei Äste
* je Ast: Route, Umstiege, Ziel

## Unten

* kompakte Hinweise / Status

Das ist die endgültige Zielstruktur für den MVP.

---

# 17. Tool-Beschreibung

**RouteSnap** ist ein unabhängiger Python-Renderer für ÖPNV-Verbindungen.
Er nimmt das normalisierte JSON deines bestehenden `vbb.py`-Tools als Input, ergänzt um die Leg-Felder `type` und `duration_min`, und erzeugt daraus eine mobile, visuell hochwertige SVG- oder PNG-Grafik im dunklen Neon-/Linear-Stil.

Im MVP zeigt RouteSnap maximal zwei Verbindungen:

* bei einer Verbindung als vertikalen Routen-Graph
* bei zwei Verbindungen als gemeinsamen Stamm mit einem Split-Punkt und zwei Ästen bis zum Ziel

Start und Ziel sind gefüllte Knoten, Umstiege ungefüllte Knoten, Transit-Strecken sind farbige Neon-Linien und Fußwege gestrichelte Linien. Oben stehen Dauer, Umstiege, Fußwegzeit und Abfahrts-/Ankunftszeit, unten kompakte Hinweise.

Damit ist RouteSnap **klar getrennt vom Routing**, direkt **agententauglich** und ohne großen Umbau mit deinem bestehenden VBB-Script kombinierbar.

---


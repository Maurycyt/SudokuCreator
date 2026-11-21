# Sudoku Creator — dokument projektowy

Generator sudoku o zadanym poziomie trudności, oparty na solverze, który rozwiązuje **jak człowiek**: stosuje kolejne strategie od najłatwiejszej, a każdy ruch potrafi wyjaśnić i zwizualizować.

Język: C++17. GUI: Dear ImGui (GLFW + OpenGL), za abstrakcją `IPainter`.

---

## Spis treści

1. [Cele i założenia](#1-cele-i-założenia)
2. [Architektura](#2-architektura)
3. [Pojęcia](#3-pojęcia)
4. [Model planszy](#4-model-planszy)
5. [Wyjaśnienia (model wizualizacji)](#5-wyjaśnienia-model-wizualizacji)
6. [Format strategii](#6-format-strategii)
7. [Solver](#7-solver)
8. [Katalog strategii](#8-katalog-strategii)
9. [Przykładowe implementacje](#9-przykładowe-implementacje)
10. [Walidacja i testy](#10-walidacja-i-testy)
11. [Ocena trudności](#11-ocena-trudności)
12. [Generator](#12-generator)
13. [GUI](#13-gui)
14. [Decyzje projektowe](#14-decyzje-projektowe)
15. [Plan implementacji](#15-plan-implementacji)
16. [Otwarte kwestie](#16-otwarte-kwestie)

---

## 1. Cele i założenia

- **Solver ludzki, nie algorytmiczny.** Rozwiązanie to sekwencja kroków, z których każdy wynika z nazwanej strategii, możliwej do zastosowania przez człowieka.
- **Strategie jako wskaźniki na funkcje.** Każda strategia to czysta funkcja `find(const Board&) → optional<Step>` plus metadane (nazwa, waga trudności). Nowa strategia = jedna funkcja + jedna linia w rejestrze.
- **Każdy krok się tłumaczy.** Strategia zwraca razem z ruchem kompletne dane do wizualizacji (klatki, podświetlenia, tekst). GUI nie wie nic o konkretnych strategiach.
- **Trudność wynika z rozwiązania.** Poziom sudoku liczony jest z logu kroków (najtrudniejsza użyta strategia, liczba trudnych kroków itp.).
- **Rozwiązywalność z konstrukcji.** Generator przyjmuje tylko sudoku, które solver rozwiązuje bez zgadywania. Każde wydane sudoku jest więc rozwiązywalne zaimplementowanymi strategiami.

Poza zakresem (na razie): warianty sudoku (Killer, X-Sudoku), rozmiary inne niż 9×9.

---

## 2. Architektura

```
            ┌───────────────┐
            │   Generator   │  pełna plansza → usuwanie cyfr → ocena
            └──────┬────────┘
                   │ używa
     ┌─────────────▼─────────────┐        ┌──────────────────────┐
     │          Solver           │───────▶│ Uniqueness checker   │
     │  pętla po strategiach     │        │ (backtracking, ≤2)   │
     └──────┬──────────────┬─────┘        └──────────────────────┘
            │ find(board)  │ SolveResult (kroki + snapshoty)
     ┌──────▼──────┐  ┌────▼─────────┐
     │ Strategie   │  │   Rating     │
     │ (rejestr)   │  └──────────────┘
     └──────┬──────┘
            │ Step { efekty, Explanation }
     ┌──────▼──────────────────────────┐
     │ GUI: snapshot[i] + frame[j]     │
     │ renderer → IPainter (ImGui/SVG) │
     └─────────────────────────────────┘
```

Przepływ danych dla jednego kroku:

```
Solver ── find(board) ──▶ Strategy ──▶ optional<Step>
                                         • placements
                                         • eliminations
                                         • explanation (frames)
Solver: snapshot(board) → aplikuj efekty → zapisz Step
GUI:    rysuj snapshots[i] + steps[i].explanation.frames[j]
```

### Struktura katalogów

```
SudokuSolver/
  core/         board.h  board.cpp  units.h  units.cpp  board_utils.h
  explain/      explanation.h  builder.h  tokens.h  validate.h  validate.cpp
  strategies/   strategy.h  registry.cpp
                singles.cpp  intersections.cpp  subsets.cpp  fish.cpp
                single_digit.cpp  wings.cpp  uniqueness.cpp  chains.cpp  als.cpp
                forcing.cpp
  solver/       solver.h  solver.cpp  rating.h  rating.cpp
                uniqueness.h  uniqueness.cpp  generator.h  generator.cpp
  gui/          painter.h  imgui_painter.cpp  svg_painter.cpp
                theme.h  board_view.cpp  text_view.cpp  app.cpp
  tests/        test_board.cpp  test_strategies.cpp  test_solver.cpp  puzzles/
```

Zależności tylko w dół: `gui → solver → strategies → explain → core`. `core` i `explain` nie zależą od niczego.

---

## 3. Pojęcia

| Pojęcie | Znaczenie |
|---|---|
| **Jednostka** (unit) | wiersz, kolumna albo kwadrat 3×3. Jest ich 27. |
| **Widzi** (sees) | dwie różne komórki leżą we wspólnej jednostce, więc nie mogą mieć tej samej cyfry |
| **Sąsiedzi** (peers) | 20 komórek widzianych przez daną komórkę |
| **Kandydaci** (pencil marks) | cyfry, które jeszcze mogą stać w pustej komórce |
| **Silny link** | para kandydatów, z których **co najmniej jeden** jest prawdziwy (cyfra ma w jednostce 2 miejsca albo komórka ma 2 kandydatów) |
| **Słaby link** | para kandydatów, z których **co najwyżej jeden** jest prawdziwy |
| **Krok** (step) | jeden ruch solvera: wpisanie cyfr i/lub skreślenie kandydatów, z wyjaśnieniem |
| **Klatka** (frame) | jeden etap wyjaśnienia kroku (np. „przyczyna”, „skutek”) |

### Notacja

- Komórki: `r1c1` … `r9c9` (wiersz, kolumna, od 1).
- Jednostki: `r3` (wiersz), `c5` (kolumna), `b2` (kwadrat, numerowane wierszami od lewego górnego).
- Wewnętrznie: komórka `0..80` (`cell = row*9 + col`), jednostka `0..26` (`0–8` wiersze, `9–17` kolumny, `18–26` kwadraty), cyfra `1..9`.

Notacja `r/c/b` jest standardowa wśród sudokowiczów i omija polską odmianę w tekstach wyjaśnień.

---

## 4. Model planszy

### 4.1 Kandydaci jako maska bitowa

```cpp
using Mask = uint16_t;                       // bity 1..9; bit 0 nieużywany
inline Mask bit(int d) { return Mask(1u << d); }
constexpr Mask ALL = 0x3FE;                  // bity 1..9

inline int  popcount(Mask m) { return __builtin_popcount(m); }
inline int  lowestDigit(Mask m) { return __builtin_ctz(m); }
```

### 4.2 Tablice prekomputowane

```cpp
// units.h — wypełniane raz przez initUnits()
extern int UNITS[27][9];      // komórki każdej jednostki
extern int UNITS_OF[81][3];   // {wiersz, kolumna, kwadrat} danej komórki
extern int PEERS[81][20];     // sąsiedzi
void initUnits();
```

### 4.3 Board

```cpp
struct Board {
    uint8_t value[81] = {};   // 0 = puste
    Mask    cand[81]  = {};   // kandydaci; 0 dla wypełnionych
    uint8_t given[81] = {};   // 1 = cyfra podana w zadaniu (do rysowania)

    static Board fromString(std::string_view s81);   // '.' lub '0' = puste
    std::string  toString() const;

    void initCandidates();         // liczy kandydatów od zera
    void place(int c, int d);      // wpisuje, czyści kandydatów c i usuwa d u sąsiadów
    void eliminate(int c, int d);  // cand[c] &= ~bit(d)

    bool solved() const;           // wszystkie 81 wypełnione
    bool contradiction() const;    // pusta komórka bez kandydatów
                                   // lub cyfra bez miejsca w jednostce
};
```

Uwagi:

- `place()` automatycznie usuwa cyfrę z kandydatów sąsiadów. Odpowiada to temu, co człowiek robi „w głowie” po wpisaniu cyfry, i nie jest liczone jako osobny krok.
- Snapshot planszy ma 81 × 4 bajty. Kopiowanie przed każdym krokiem jest tanie.

### 4.4 Referencje

```cpp
struct CellRef { int cell; };
struct CandRef { int cell; int digit;
                 bool operator==(const CandRef&) const = default; };
```

### 4.5 Helpery (board_utils.h)

```cpp
inline int rowOf(int c) { return c / 9; }
inline int colOf(int c) { return c % 9; }
inline int boxOf(int c) { return (c / 27) * 3 + (c % 9) / 3; }
inline int rowUnit(int r) { return r; }
inline int colUnit(int c) { return 9 + c; }
inline int boxUnit(int b) { return 18 + b; }
enum class UnitKind { Row, Col, Box };
inline UnitKind unitKind(int u) { return u < 9 ? UnitKind::Row : u < 18 ? UnitKind::Col : UnitKind::Box; }

bool sees(int a, int b);                                     // wspólna jednostka, a != b
bool unitHas(const Board& b, int u, int d);                  // d już wpisana w u
std::vector<int> cellsWith(const Board& b, int u, int d);    // komórki u z kandydatem d
int  commonLine(const std::vector<int>& cells);              // wspólny wiersz/kolumna albo -1
std::vector<int> commonPeers(const std::vector<int>& cells); // komórki widzące wszystkie

struct Excluder { int cell; int unit; };
// Kto wyklucza d w komórce c: wpisana d we wspólnej jednostce, poza skipUnit.
// nullopt = kandydat skreślony wcześniej przez inną strategię.
std::optional<Excluder> findExcluder(const Board& b, int c, int d, int skipUnit);

std::string cellName(int c);   // "r3c5"
std::string unitName(int u);   // "r3" / "c5" / "b2"
```

---

## 5. Wyjaśnienia (model wizualizacji)

**Zasada:** strategia nie rysuje, tylko **opisuje**. Zwraca dane z rolami, a jeden ogólny renderer w GUI rysuje każdą strategię.

### 5.1 Role (semantyka, nie kolory)

```cpp
enum class Role {
    Unit,            // jednostka, w której coś się dzieje
    Base, Cover,     // ryby: jednostki bazowe / przykrywające; Cover też w Pointing
    Excluder,        // komórka-źródło wykluczenia
    Blocked,         // komórka wykluczona wcześniejszym skreśleniem
    Pattern,         // kandydaci tworzący wzór
    Pivot, Wing,     // skrzydła (XY-Wing, XYZ-Wing, W-Wing)
    ColorA, ColorB,  // coloring, łańcuchy (on/off)
    Target,          // komórka, w której nastąpi efekt
    Eliminated,      // skreślany kandydat
    Placed           // wpisywana cyfra
};
```

Mapowanie `Role → kolor` robi motyw (`Theme`) w GUI.

### 5.2 Prymitywy, klatka, wyjaśnienie

```cpp
struct UnitMark { int unit;     Role role; std::string note; };
struct CellMark { int cell;     Role role; std::string note; };
struct CandMark { CandRef cand; Role role; std::string note; };
struct Ray      { int fromCell; int unit; int digit; };   // linia wykluczenia
struct Link     { CandRef a, b; bool strong; };           // strzałka między kandydatami

struct Frame {
    std::vector<UnitMark> units;
    std::vector<CellMark> cells;
    std::vector<CandMark> cands;
    std::vector<Ray>      rays;
    std::vector<Link>     links;
    std::string           text;    // z tokenami, patrz 5.3

    // dla hover: wszystkie adnotacje dotyczące komórki/kandydata
    // (cellMarks i unitMarks zawierające komórkę, candMarks dla danego kandydata)
    struct HoverInfo { Role role; std::string_view note; };
    std::vector<HoverInfo> annotationsAt(int cell, int digit) const;
};

struct Explanation { std::vector<Frame> frames; };
```

| Prymityw | Rysowanie |
|---|---|
| `UnitMark` | tło całej jednostki |
| `CellMark` | tło komórki |
| `CandMark` | kolorowe kółko pod małą cyfrą kandydata; `Eliminated` dodatkowo przekreślenie |
| `Ray` | linia od środka komórki-źródła przez jednostkę; pokazuje, skąd wzięło się wykluczenie |
| `Link` | strzałka między środkami kandydatów; silny = ciągła, słaby = przerywana |

`note` (opcjonalne) to krótki opis wyświetlany w dymku po najechaniu myszą, np. „5 w r2c4 wyklucza wiersz 2”.

### 5.3 Tokeny w tekście

```cpp
namespace T {
    inline std::string cell(int c)  { return "{cell:"  + std::to_string(c) + "}"; }  // → r3c5
    inline std::string unit(int u)  { return "{unit:"  + std::to_string(u) + "}"; }  // → r3 / c5 / b2
    inline std::string digit(int d) { return "{d:"     + std::to_string(d) + "}"; }  // → 5
}

struct Ref { enum Kind { Cell, Unit, Digit } kind; int value; };
struct TextSeg { std::string text; std::optional<Ref> ref; };
std::vector<TextSeg> parseTokens(const std::string& s);
```

GUI zamienia tokeny na nazwy i robi z nich elementy interaktywne: najechanie podświetla komórkę lub jednostkę na planszy.

### 5.4 Klatki

- Proste strategie: **2 klatki** — *przyczyna* (wzór) i *skutek* (efekt).
- Wingi: 2–3 klatki (pivot → skrzydła → eliminacja).
- Łańcuchy: **1 klatka na ogniwo** + klatka z eliminacją.
- Ostatnia klatka zawsze zawiera wszystkie efekty kroku (`Placed` / `Eliminated`).

### 5.5 ExplainBuilder

```cpp
class ExplainBuilder {
    Explanation e;
    Frame& cur() { return e.frames.back(); }
public:
    ExplainBuilder& frame(std::string text) {
        e.frames.emplace_back(); cur().text = std::move(text); return *this;
    }
    // kopiuje wszystkie adnotacje poprzedniej klatki (bez tekstu)
    ExplainBuilder& keepPrevious() {
        auto text = std::move(cur().text);
        cur() = e.frames[e.frames.size() - 2];
        cur().text = std::move(text);
        return *this;
    }
    ExplainBuilder& unit(int u, Role r = Role::Unit, std::string note = {})
        { cur().units.push_back({u, r, std::move(note)}); return *this; }
    ExplainBuilder& cell(int c, Role r, std::string note = {})
        { cur().cells.push_back({c, r, std::move(note)}); return *this; }
    ExplainBuilder& cand(int c, int d, Role r, std::string note = {})
        { cur().cands.push_back({{c, d}, r, std::move(note)}); return *this; }
    ExplainBuilder& ray(int from, int u, int d)
        { cur().rays.push_back({from, u, d}); return *this; }
    ExplainBuilder& link(CandRef a, CandRef b, bool strong)
        { cur().links.push_back({a, b, strong}); return *this; }
    Explanation build() { return std::move(e); }
};
```

---

## 6. Format strategii

### 6.1 Interfejs

```cpp
struct Step;
using FindFn = std::optional<Step> (*)(const Board&);    // wskaźnik na funkcję

struct Strategy {
    const char* id;          // "pointing" — stabilny identyfikator (testy, zapis)
    const char* name;        // "Pointing" — nazwa do GUI
    double      difficulty;  // waga trudności (skala w stylu Sudoku Explainer)
    FindFn      find;
};

struct Step {
    const Strategy*      strategy = nullptr;  // ustawia solver
    std::vector<CandRef> placements;          // wpisania (tylko single)
    std::vector<CandRef> eliminations;        // skreślenia
    Explanation          explanation;         // wypełnia strategia
};
```

### 6.2 Kontrakt strategii

1. **Czysta funkcja.** Dostaje `const Board&`, niczego nie modyfikuje, nie ma stanu globalnego.
2. **Deterministyczna.** Ten sam stan planszy daje ten sam wynik (stała kolejność przeszukiwania).
3. **Jeden ruch.** Zwraca pierwszy znaleziony ruch albo `std::nullopt`.
4. **Ruch musi coś zmieniać.** `placements` lub `eliminations` niepuste. Wzór bez efektu = szukaj dalej. (Inaczej solver się zapętli.)
5. **Wyjaśnienie budowane dopiero po znalezieniu ruchu**, nie w trakcie przeszukiwania.
6. **Ostatnia klatka zawiera efekty**: każde wpisanie jako `CellMark{Placed}`, każde skreślenie jako `CandMark{Eliminated}`.
7. **Kolejność przeszukiwania naśladuje człowieka**, np. Hidden Single najpierw w kwadratach.

### 6.3 Schemat każdej strategii

```
for (każde miejsce, gdzie może wystąpić wzór):
    znajdź wzór helperami
    jeśli brak → continue
    policz efekty
    jeśli efekty puste → continue
    zbuduj Step: efekty + ExplainBuilder (przyczyna → skutek)
    return Step
return nullopt
```

### 6.4 Silniki generyczne

Wiele strategii to warianty jednego algorytmu. Implementujemy generyczny silnik i cienkie strategie na nim (z różną wagą):

| Silnik | Strategie |
|---|---|
| `findNakedSubset<N>` | Naked Pair / Triple / Quad |
| `findHiddenSubset<N>` | Hidden Pair / Triple / Quad |
| `findFish<N>` | X-Wing / Swordfish / Jellyfish |
| łańcuchy jednej cyfry (graf silnych/słabych linków) | Skyscraper, 2-String Kite, X-Chain, Simple Coloring |
| łańcuchy bivalue | XY-Wing, XY-Chain, W-Wing |
| AIC | ogólne łańcuchy |

```cpp
template<int N> std::optional<Step> findNakedSubset(const Board&);
template<int N> std::optional<Step> findHiddenSubset(const Board&);
template<int N> std::optional<Step> findFish(const Board&);
```

Mimo że AIC znalazłby ruchy Skyscrapera czy XY-Winga, proste wzory zostają **osobnymi, wcześniejszymi** strategiami: trudność liczy się trafniej, a wyjaśnienia są czytelniejsze („to jest Skyscraper”, nie „łańcuch długości 4”).

### 6.5 Rejestr

```cpp
// registry.cpp
const std::vector<Strategy>& allStrategies() {
    static const std::vector<Strategy> S = {
        {"full_house",         "Full House",              1.0, findFullHouse},
        {"hidden_single_box",  "Hidden Single (kwadrat)", 1.2, findHiddenSingleBox},
        {"hidden_single_line", "Hidden Single (linia)",   1.5, findHiddenSingleLine},
        {"naked_single",       "Naked Single",            2.3, findNakedSingle},
        {"pointing",           "Pointing",                2.6, findPointing},
        {"claiming",           "Claiming",                2.8, findClaiming},
        {"naked_pair",         "Naked Pair",              3.0, findNakedSubset<2>},
        {"x_wing",             "X-Wing",                  3.2, findFish<2>},
        {"hidden_pair",        "Hidden Pair",             3.4, findHiddenSubset<2>},
        {"naked_triple",       "Naked Triple",            3.6, findNakedSubset<3>},
        {"swordfish",          "Swordfish",               3.8, findFish<3>},
        {"hidden_triple",      "Hidden Triple",           4.0, findHiddenSubset<3>},
        {"skyscraper",         "Skyscraper",              4.0, findSkyscraper},
        {"two_string_kite",    "2-String Kite",           4.1, findTwoStringKite},
        {"xy_wing",            "XY-Wing",                 4.2, findXYWing},
        {"w_wing",             "W-Wing",                  4.4, findWWing},
        {"xyz_wing",           "XYZ-Wing",                4.4, findXYZWing},
        {"unique_rect_1",      "Unique Rectangle 1",      4.5, findUniqueRect1},
        {"naked_quad",         "Naked Quad",              5.0, findNakedSubset<4>},
        {"jellyfish",          "Jellyfish",               5.2, findFish<4>},
        {"hidden_quad",        "Hidden Quad",             5.4, findHiddenSubset<4>},
        {"simple_coloring",    "Simple Coloring",         6.5, findSimpleColoring},
        {"x_chain",            "X-Chain",                 6.6, findXChain},
        {"xy_chain",           "XY-Chain",                6.8, findXYChain},
        {"aic",                "AIC",                     7.0, findAIC},
        {"als_xz",             "ALS-XZ",                  7.5, findALSXZ},
        {"forcing_chain",      "Forcing Chains",          8.0, findForcingChain},
        {"nishio",             "Nishio",                  8.5, findNishio},
        {"guess",              "Guess",                  10.0, findGuess},   // bezpiecznik
    };
    return S;
}

// warianty zestawów
std::vector<Strategy> strategiesUpTo(double maxDifficulty);
std::vector<Strategy> strategiesWithout(std::initializer_list<const char*> ids);
```

Wagi są orientacyjne; do kalibracji (patrz [Otwarte kwestie](#16-otwarte-kwestie)).

---

## 7. Solver

```cpp
struct SolveResult {
    std::vector<Step>  steps;
    std::vector<Board> snapshots;   // snapshots[i] = plansza PRZED steps[i]
    Board              final;
    bool               stuck = false;          // żadna strategia nic nie znalazła
    bool               contradiction = false;  // plansza sprzeczna
};

SolveResult solve(Board b, const std::vector<Strategy>& strategies) {
    SolveResult r;
    b.initCandidates();
    while (!b.solved()) {
        if (b.contradiction()) { r.contradiction = true; break; }

        std::optional<Step> step;
        for (const auto& st : strategies)               // zawsze od najłatwiejszej
            if ((step = st.find(b))) { step->strategy = &st; break; }
        if (!step) { r.stuck = true; break; }

        r.snapshots.push_back(b);
        for (auto [c, d] : step->placements)   b.place(c, d);
        for (auto [c, d] : step->eliminations) b.eliminate(c, d);
        r.steps.push_back(std::move(*step));
    }
    r.final = b;
    return r;
}
```

Zasady:

- Po każdym ruchu solver **wraca na początek listy**. Dzięki temu zawsze używa najłatwiejszej możliwej strategii, tak jak człowiek.
- Typowy rytm: single → (brak singli) → eliminacja → eliminacja → single odblokowany przez skreślenia → …
- Tylko single wpisują cyfry; wszystkie trudniejsze strategie skreślają kandydatów.

### Sprawdzanie jednoznaczności

Osobny, szybki solver algorytmiczny (backtracking z MRV albo Dancing Links), liczący rozwiązania do 2:

```cpp
int countSolutions(const Board& b, int limit = 2);
```

Służy wyłącznie jako narzędzie weryfikacji w generatorze, nie jako „rozwiązanie” pokazywane użytkownikowi.

---

## 8. Katalog strategii

Kolejność = kolejność w rejestrze. Waga orientacyjna (skala w stylu Sudoku Explainer).

### Poziom 1 — Single (wpisują cyfrę)

| Strategia | Waga | Reguła |
|---|---|---|
| **Full House** | 1.0 | W jednostce jedno puste pole → brakująca cyfra. |
| **Hidden Single (kwadrat)** | 1.2 | Cyfra `d` ma w kwadracie jedno możliwe miejsce (pozostałe wykluczają wiersze/kolumny z `d`) → wpisz. |
| **Hidden Single (linia)** | 1.5 | To samo w wierszu/kolumnie. |
| **Naked Single** | 2.3 | Komórka ma jednego kandydata → wpisz. Dla człowieka trudniejsze, bo trzeba zebrać cyfry z 3 jednostek. |

### Poziom 2 — Przecięcia (skreślają)

| Strategia | Waga | Reguła |
|---|---|---|
| **Pointing** | 2.6 | W kwadracie kandydaci `d` leżą tylko w jednym wierszu/kolumnie → skreśl `d` w reszcie tej linii. |
| **Claiming** (Box/Line Reduction) | 2.8 | W wierszu/kolumnie kandydaci `d` leżą tylko w jednym kwadracie → skreśl `d` w reszcie kwadratu. |

### Poziom 3 — Podzbiory (skreślają)

| Strategia | Waga | Reguła |
|---|---|---|
| **Naked Pair/Triple/Quad** | 3.0 / 3.6 / 5.0 | N komórek jednostki ma łącznie N kandydatów → skreśl te cyfry w reszcie jednostki. Komórki nie muszą mieć wszystkich N (np. `{1,2}{2,3}{1,3}`). |
| **Hidden Pair/Triple/Quad** | 3.4 / 4.0 / 5.4 | N cyfr występuje w jednostce tylko w tych samych N komórkach → usuń z nich innych kandydatów. |

### Poziom 4 — Ryby i wzory jednej cyfry (skreślają)

| Strategia | Waga | Reguła |
|---|---|---|
| **X-Wing** | 3.2 | `d` w 2 wierszach (bazach) ma po 2 miejsca w tych samych 2 kolumnach → skreśl `d` w tych kolumnach poza bazami. Także z zamianą wierszy/kolumn. |
| **Swordfish / Jellyfish** | 3.8 / 5.2 | To samo dla 3/4 baz: w każdej `d` ma 2..N miejsc, łącznie w N kolumnach. |
| **Skyscraper** | 4.0 | 2 wiersze z dokładnie 2 miejscami dla `d`; jeden koniec obu w tej samej kolumnie (podstawa), drugie nie (wierzchołki). Któryś wierzchołek jest `d` → skreśl `d` w polach widzących oba wierzchołki. |
| **2-String Kite** | 4.1 | Wiersz i kolumna, każda z dokładnie 2 miejscami dla `d`, po jednym końcu w tym samym kwadracie (różne komórki). Któryś z wolnych końców jest `d` → skreśl `d` w polu widzącym oba. |

### Poziom 5 — Skrzydła

| Strategia | Waga | Reguła |
|---|---|---|
| **XY-Wing** | 4.2 | Pivot `{X,Y}` widzi skrzydła `{X,Z}` i `{Y,Z}`. Któreś skrzydło jest Z → skreśl Z w polach widzących oba skrzydła. |
| **XYZ-Wing** | 4.4 | Pivot `{X,Y,Z}`, skrzydła `{X,Z}`, `{Y,Z}` → skreśl Z w polach widzących wszystkie trzy. |
| **W-Wing** | 4.4 | Dwie niewidzące się komórki `{X,Y}` połączone silnym linkiem na X (jeden koniec widzi A, drugi B). Któraś jest Y → skreśl Y w polach widzących obie. |

### Poziom 6 — Unikalność

| Strategia | Waga | Reguła |
|---|---|---|
| **Unique Rectangle typ 1** | 4.5 | 4 komórki w 2 wierszach, 2 kolumnach, 2 kwadratach; trzy mają `{a,b}`, czwarta `{a,b,…}` → usuń a, b z czwartej (inaczej 2 rozwiązania). **Zakłada jednoznaczność** — nie używać przy jej weryfikacji. |

### Poziom 7 — Łańcuchy

| Strategia | Waga | Reguła |
|---|---|---|
| **Simple Coloring** | 6.5 | Sieć silnych linków dla `d`, kolory A/B na przemian. *Color Trap*: pole widzi A i B → skreśl `d`. *Color Wrap*: dwa A się widzą → wszystkie A fałszywe. |
| **X-Chain** | 6.6 | Jedna cyfra, linki silny–słaby–…–silny; któryś koniec jest `d` → skreśl w polach widzących oba końce. |
| **XY-Chain** | 6.8 | Łańcuch komórek bivalue, sąsiednie się widzą i dzielą cyfrę; Z na obu końcach → skreśl Z w polach widzących oba końce. |
| **AIC** | 7.0 | Węzły to dowolne kandydaty, linki naprzemiennie silne/słabe, mogą zmieniać cyfrę; oba końce silne → co najmniej jeden prawdziwy. |
| **ALS-XZ** | 7.5 | Dwa ALS (N komórek, N+1 kandydatów) z restricted common X → wspólna cyfra Z jest w A lub B → skreśl Z widzące wszystkie Z z obu. |

### Poziom 8 — Ostateczność

| Strategia | Waga | Reguła |
|---|---|---|
| **Forcing Chains** | 8.0 | Dla każdego kandydata komórki (lub miejsca cyfry w jednostce) propaguj konsekwencje; wspólny wniosek wszystkich gałęzi jest prawdą. |
| **Nishio** | 8.5 | Załóż kandydata, propaguj; sprzeczność → kandydat odpada. |
| **Guess** | 10.0 | Bifurkacja / backtracking. Tylko bezpiecznik; generator odrzuca sudoku, które tego wymaga. |

### Hierarchia uogólnień

```
Skyscraper, 2-String Kite  ⊂  X-Chain  ⊂  AIC
XY-Wing                    ⊂  XY-Chain ⊂  AIC
X-Wing ⊂ Swordfish ⊂ Jellyfish            (findFish<N>)
Naked/Hidden Pair ⊂ Triple ⊂ Quad         (findNakedSubset<N> / findHiddenSubset<N>)
```

### Uwaga o kompletności

Żaden skończony zestaw „ludzkich” strategii nie gwarantuje rozwiązania każdego sudoku. Strategie z poziomów 1–5 rozwiązują praktycznie wszystkie sudoku z gazet; z łańcuchami — ponad 99,9% sensownych sudoku. Gwarancję daje generator: wydaje tylko sudoku rozwiązywalne zaimplementowanymi strategiami bez `Guess`.

---

## 9. Przykładowe implementacje

### 9.1 Hidden Single w kwadracie

```cpp
std::optional<Step> findHiddenSingleBox(const Board& b) {
    for (int box = 0; box < 9; ++box) {
        int u = boxUnit(box);
        for (int d = 1; d <= 9; ++d) {
            if (unitHas(b, u, d)) continue;
            auto cells = cellsWith(b, u, d);
            if (cells.size() != 1) continue;
            int target = cells[0];

            Step s;
            s.placements = {{target, d}};

            ExplainBuilder eb;
            eb.frame("W " + T::unit(u) + " cyfra " + T::digit(d) +
                     " pasuje tylko w jedno miejsce. Pozostałe pola wykluczają:")
              .unit(u);

            std::set<std::pair<int,int>> drawnRays;
            for (int c : UNITS[u]) {
                if (c == target || b.value[c] != 0) continue;
                if (auto ex = findExcluder(b, c, d, u)) {
                    eb.cell(ex->cell, Role::Excluder,
                            std::to_string(d) + " w " + cellName(ex->cell) +
                            " wyklucza " + unitName(ex->unit));
                    if (drawnRays.insert({ex->cell, ex->unit}).second)
                        eb.ray(ex->cell, ex->unit, d);
                } else {
                    eb.cell(c, Role::Blocked, "skreślone wcześniejszą strategią");
                }
            }

            eb.frame("Wpisujemy " + T::digit(d) + " w " + T::cell(target) + ".")
              .keepPrevious()
              .cell(target, Role::Placed);

            s.explanation = eb.build();
            return s;
        }
    }
    return std::nullopt;
}
```

W GUI: klatka 1 — podświetlony kwadrat, cyfry-źródła z liniami przecinającymi kwadrat, jedno pole bez linii; klatka 2 — to samo plus wpisana cyfra.

### 9.2 Pointing

```cpp
std::optional<Step> findPointing(const Board& b) {
    for (int box = 0; box < 9; ++box) {
        int bu = boxUnit(box);
        for (int d = 1; d <= 9; ++d) {
            auto cells = cellsWith(b, bu, d);
            if (cells.size() < 2) continue;
            int line = commonLine(cells);
            if (line < 0) continue;

            Step s;
            for (int c : UNITS[line])
                if (boxOf(c) != box && (b.cand[c] & bit(d)))
                    s.eliminations.push_back({c, d});
            if (s.eliminations.empty()) continue;

            ExplainBuilder eb;
            eb.frame("W " + T::unit(bu) + " cyfra " + T::digit(d) +
                     " może stać tylko w " + T::unit(line) + ".")
              .unit(bu);
            for (int c : cells) eb.cand(c, d, Role::Pattern);

            eb.frame(T::unit(bu) + " musi mieć " + T::digit(d) + ", więc w reszcie " +
                     T::unit(line) + " jej nie będzie.")
              .keepPrevious()
              .unit(line, Role::Cover);
            for (auto e : s.eliminations)
                eb.cand(e.cell, d, Role::Eliminated, "skreślone przez Pointing");

            s.explanation = eb.build();
            return s;
        }
    }
    return std::nullopt;
}
```

### 9.3 Szkic: generyczna ryba

```cpp
// Dla cyfry d i orientacji (bazy = wiersze lub kolumny):
//   kandydaci bazowi: linie, w których d ma 2..N miejsc (maska pozycji 9-bitowa)
//   dla każdej kombinacji N baz: suma masek ma dokładnie N bitów → to są cover
//   efekt: d skreślone w liniach cover poza bazami
//   wyjaśnienie: klatka 1 – Base + Pattern (+ linki w bazach),
//                klatka 2 – keepPrevious + Cover + Eliminated
template<int N> std::optional<Step> findFish(const Board& b);
```

---

## 10. Walidacja i testy

### 10.1 Walidator wyjaśnień

Uruchamiany w testach dla każdego kroku każdej strategii:

```cpp
struct ValidationError { std::string message; };
std::vector<ValidationError> validateStep(const Board& before, const Step& s);
```

Sprawdza:

- `placements` lub `eliminations` niepuste;
- każde wpisanie jest kandydatem w `before`; każde skreślenie jest kandydatem w `before`;
- ostatnia klatka zawiera dokładnie te efekty jako `Placed` / `Eliminated` (i nic więcej z tymi rolami);
- każda klatka ma niepusty tekst, tokeny parsują się poprawnie;
- kandydaci użyci w `Link` / `CandMark` (poza `Eliminated` w ostatniej klatce) istnieją w `before`;
- (opcjonalnie) efekt jest zgodny z prawdziwym rozwiązaniem — skreślenie nie usuwa cyfry rozwiązania, wpisanie jej odpowiada.

Ostatni punkt łapie błędy logiczne strategii: na zestawie sudoku ze znanym rozwiązaniem żadna strategia nie może skreślić prawdziwej cyfry.

### 10.2 Testy strategii

Każda strategia ma testy na planszach z oczekiwanym ruchem (przykłady z SudokuWiki, HoDoKu):

```cpp
TEST(Pointing, eliminates_in_row) {
    Board b = Board::fromString("...");
    b.initCandidates();
    auto s = findPointing(b);
    ASSERT_TRUE(s);
    EXPECT_EQ(s->eliminations, (std::vector<CandRef>{{43, 5}, {44, 5}}));
    EXPECT_TRUE(validateStep(b, *s).empty());
}
```

Uwaga: przykłady z zewnątrz często mają kandydatów już po wcześniejszych eliminacjach. Format wejścia testów powinien umożliwiać podanie kandydatów wprost (np. 81 pól z listą kandydatów).

### 10.3 Testy solvera

- Zbiór sudoku o znanym poziomie → solver rozwiązuje, `final` zgodny z rozwiązaniem.
- Sudoku wymagające konkretnej techniki → w krokach występuje ta strategia.
- Fuzzing: losowe sudoku z generatora → `validateStep` dla każdego kroku.

---

## 11. Ocena trudności

```cpp
struct Rating {
    double maxDifficulty;        // najtrudniejszy krok — wąskie gardło, główny wyznacznik
    int    hardSteps;            // kroki z wagą powyżej progu (np. > 2.5)
    double totalDifficulty;      // suma wag kroków eliminacyjnych
    int    stalls;               // ile razy zabrakło singli
    std::map<std::string,int> strategyCounts;
    Level  level;
};

Rating rate(const SolveResult& r);
```

- Liczba wpisań jest stała (81 − liczba podanych), więc liczy się głównie kroki eliminacyjne i ich wagi.
- **Przestoje** (`stalls`): ile razy w ogóle zabrakło singli; im więcej i im trudniejsze strategie wtedy, tym trudniej.
- Opcjonalnie: liczba dostępnych singli w danym momencie (więcej wyborów = łatwiej). Wymaga funkcji `countAll` przy strategii.

### Poziomy

| Poziom | maxDifficulty |
|---|---|
| Łatwy | ≤ 1.5 (tylko Full House i Hidden Single) |
| Średni | ≤ 2.8 (+ Naked Single, Pointing, Claiming) |
| Trudny | ≤ 4.5 (podzbiory, X-Wing, Swordfish, wingi, UR) |
| Ekspert | ≤ 7.0 (Jellyfish, quady, proste łańcuchy, AIC) |
| Ekstremalny | > 7.0, bez `Guess` |

---

## 12. Generator

```cpp
struct GenerateOptions {
    Level  target;
    bool   symmetric = true;                   // usuwanie parami symetrycznymi
    std::optional<std::string> requireStrategy; // np. "x_wing" — rozwiązanie musi jej użyć
    uint64_t seed;
    int    maxAttempts = 200;
};

std::optional<Board> generate(const GenerateOptions& opt);
```

Algorytm:

1. **Pełna plansza**: losowy backtracking z przetasowanymi cyframi.
2. **Usuwanie cyfr** w losowej kolejności (parami symetrycznymi). Po każdym usunięciu:
   - `countSolutions(b, 2) != 1` → przywróć;
   - solver strategiczny (zestaw **bez Unique Rectangle i bez Guess**) się zablokował albo `maxDifficulty` > górna granica poziomu → przywróć.
3. Gdy nic więcej nie da się usunąć: jeśli `maxDifficulty` w przedziale poziomu (i ewentualnie użyto `requireStrategy`) → zwróć. W przeciwnym razie nowa próba.

W praktyce wystarcza kilka do kilkudziesięciu prób. Optymalizacja na później: hill-climbing (dodawanie/usuwanie pojedynczych cyfr w kierunku docelowej trudności).

Dlaczego bez Unique Rectangle przy generowaniu: UR zakłada, że rozwiązanie jest jedno. Do oceny gotowego, jednoznacznego sudoku można go używać.

---

## 13. GUI

### 13.1 Układ okna

```
┌────────────────────────────────────┬──────────────────┐
│                                    │ Kroki:           │
│         PLANSZA 9×9                │  1 Hidden Single │
│   (cyfry, kandydaci, kolory,       │  2 Hidden Single │
│    linie, strzałki)                │ ▶3 Pointing      │
│                                    │  4 Naked Pair    │
│                                    │  ...             │
├────────────────────────────────────┤                  │
│ Pointing (2.6) · klatka 1/2        │ Trudność: 3.2    │
│ W b4 cyfra 5 może stać tylko w r5. │ Poziom: Trudny   │
├────────────────────────────────────┤ [Generuj ▼Trudny]│
│ [◀◀ krok] [◀ klatka] [klatka ▶] [krok ▶▶] │ [Wczytaj]  │
└────────────────────────────────────┴──────────────────┘
```

Klawiatura: ← → kroki, ↑ ↓ klatki.

### 13.2 Elementy planszy

| Element | Wygląd |
|---|---|
| Siatka | cienkie linie, co 3 grubsze |
| Cyfry podane | duże, czarne |
| Cyfry wpisane przez solver | duże, inny kolor (np. niebieskie) |
| Kandydaci | małe cyfry w mini-siatce 3×3 (1 lewy górny, 9 prawy dolny) |
| Tło jednostki / komórki | kolor wg `Role` |
| Podświetlony kandydat | kolorowe kółko pod cyfrą |
| Eliminacja | czerwone kółko + przekreślenie |
| Ray / Link | linia; silny link ciągły, słaby przerywany, ze strzałką |
| Hover | obwódka elementu wskazanego w tekście |

### 13.3 IPainter

```cpp
struct PointF { float x, y; };
struct RectF  { float x, y, w, h; };
struct Color  { uint8_t r, g, b, a; };

struct IPainter {
    virtual void fillRect(RectF r, Color c) = 0;
    virtual void strokeRect(RectF r, Color c, float width) = 0;
    virtual void line(PointF a, PointF b, Color c, float width, bool dashed = false) = 0;
    virtual void fillCircle(PointF center, float radius, Color c) = 0;
    virtual void text(PointF center, const std::string& s, float size, Color c) = 0;
    virtual void arrowHead(PointF tip, PointF from, Color c) = 0;
    virtual ~IPainter() = default;
};
```

Implementacje: `ImGuiPainter` (na `ImDrawList`: `AddRectFilled`, `AddLine`, `AddCircleFilled`, `AddText`), `SvgPainter` (eksport kroków do plików, dokumentacja, testy wizualne).

### 13.4 Renderer

```cpp
struct Theme {
    Color roleColor(Role r) const;    // Excluder niebieski, Pattern zielony, Eliminated czerwony…
    Color given, solved, candidate, gridThin, gridThick, hover;
};

void drawBoard(IPainter& p, const Board& b, const Frame* frame,
               const std::optional<Ref>& hover, const Theme& theme,
               PointF origin, float cellSize);
```

Kolejność warstw:

1. tła jednostek (`units`)
2. tła komórek (`cells`)
3. siatka
4. cyfry wpisane
5. kółka kandydatów (`cands`)
6. małe cyfry kandydatów
7. przekreślenia (`Eliminated`)
8. promienie (`rays`)
9. linki (`links`) ze strzałkami
10. obwódka hover

Pozycja kandydata:

```cpp
PointF candCenter(PointF origin, int cell, int d, float cellSize) {
    float x = origin.x + (cell % 9) * cellSize, y = origin.y + (cell / 9) * cellSize;
    float s = cellSize / 3;
    return { x + ((d-1) % 3 + 0.5f) * s, y + ((d-1) / 3 + 0.5f) * s };
}
```

### 13.5 Stan aplikacji

```cpp
struct AppState {
    Board       start;
    SolveResult result;          // steps + snapshots
    Rating      rating;
    int         stepIdx  = 0;
    int         frameIdx = 0;
    std::optional<Ref> hoverRef; // z tekstu
    int         previewStep = -1; // hover na liście kroków
};
```

Wyświetlane: `result.snapshots[stepIdx]` + `result.steps[stepIdx].explanation.frames[frameIdx]`. Nawigacja = zmiana indeksów, bez cofania ruchów i bez ponownego uruchamiania strategii.

### 13.6 Hover

**1. Token w tekście → podświetlenie na planszy.**

```cpp
std::optional<Ref> hoverRef;
for (auto& seg : parseTokens(frame.text)) {
    if (seg.ref) ImGui::TextColored(LINK_COLOR, "%s", seg.text.c_str());
    else         ImGui::TextUnformatted(seg.text.c_str());
    if (seg.ref && ImGui::IsItemHovered()) hoverRef = seg.ref;
    ImGui::SameLine(0, 0);
}
```

Zawijanie: dzielić zwykły tekst na słowa, przed każdym sprawdzać szerokość (`ImGui::CalcTextSize`); jeśli się nie mieści — pominąć `SameLine`.

**2. Komórka / kandydat → dymek „dlaczego”.**

```cpp
int col = int((mx - x0) / cellSize), row = int((my - y0) / cellSize);
int cell = row * 9 + col;
int sx = int(((mx - x0) - col * cellSize) / (cellSize / 3));
int sy = int(((my - y0) - row * cellSize) / (cellSize / 3));
int digit = sy * 3 + sx + 1;

// tooltip z notatkami (note) adnotacji tej komórki/kandydata w bieżącej klatce
```

**3. Krok na liście → podgląd** jego planszy i pierwszej klatki bez zmiany wybranego kroku.

### 13.7 Tryb podpowiedzi (dla gracza)

Z tych samych danych, stopniowo:

1. nazwa strategii;
2. jednostki z pierwszej klatki („szukaj tutaj”);
3. pełne wyjaśnienie.

---

## 14. Decyzje projektowe

| # | Decyzja | Uzasadnienie | Odrzucona alternatywa |
|---|---|---|---|
| D1 | Strategie to czyste funkcje (wskaźniki) `find(const Board&) → optional<Step>` | testowalność, determinizm, brak efektów ubocznych | strategie modyfikujące planszę |
| D2 | Strategia **zwraca** wszystkie dane do wizualizacji (`Explanation`) | hover i tooltipy z zapisanych danych, nawigacja = indeksy, walidacja w testach, eksport SVG, jedno miejsce rysowania | strategia rysuje bezpośrednio na przekazanej „tablicy” — rysowałaby nieudane próby, wiązałaby strategie z GUI, hover wymagałby dodatkowej pamięci, nawigacja = ponowne uruchamianie |
| D3 | Role zamiast kolorów | zmiana motywu / dark mode bez dotykania strategii | kolory w strategiach |
| D4 | Wyjaśnienie z klatek | proste strategie (2 klatki) i łańcuchy (klatka na ogniwo) w jednym modelu | jeden statyczny obraz |
| D5 | Pole `note` w adnotacjach | tooltipy „dlaczego to jest podświetlone” | tylko tekst klatki |
| D6 | Tokeny `{cell:N}` w tekście, notacja r/c/b | interaktywny tekst; brak problemu z polską odmianą | zwykły tekst |
| D7 | Solver zawsze wraca do najłatwiejszej strategii | naśladuje człowieka, trafniejsza ocena trudności | kontynuacja od bieżącej strategii |
| D8 | Proste wzory jako osobne strategie mimo AIC | trafniejsza trudność, czytelniejsze wyjaśnienia | tylko generyczne AIC |
| D9 | Generyczne silniki (`<N>`) | mniej kodu, mniej błędów | osobny kod dla każdej strategii |
| D10 | Jednoznaczność sprawdzana backtrackingiem | szybko i pewnie; to narzędzie, nie rozwiązanie | sprawdzanie solverem strategicznym |
| D11 | Unique Rectangle wyłączony przy generowaniu | zakłada jednoznaczność | — |
| D12 | Snapshoty planszy przed każdym krokiem | trywialna nawigacja, ~324 B na krok | undo przez odwracanie ruchów |
| D13 | `IPainter` jako abstrakcja | wymienny backend, eksport SVG | bezpośrednie wywołania ImGui |

---

## 15. Plan implementacji

| Etap | Zakres | Wynik |
|---|---|---|
| 1 | `core`: Board, jednostki, helpery, parser 81 znaków | testy planszy |
| 2 | `explain`: Role, Frame, Explanation, builder, tokeny, walidator | testy walidatora |
| 3 | Full House, Hidden Single (box, linia), Naked Single, solver | rozwiązuje łatwe sudoku |
| 4 | GUI MVP: siatka, cyfry, kandydaci, tła, kółka, tekst, nawigacja | podgląd singli |
| 5 | `countSolutions`, generator, rating | generuje Łatwe/Średnie |
| 6 | Pointing, Claiming, generyczne podzbiory | Średnie/Trudne |
| 7 | `findFish<N>`, rays i links w rendererze | X-Wing, Swordfish, Jellyfish |
| 8 | Skyscraper, 2-String Kite, XY-Wing, XYZ-Wing, W-Wing, UR1 | Trudne |
| 9 | Simple Coloring, X-Chain, XY-Chain, AIC | Ekspert |
| 10 | ALS-XZ, Forcing Chains, Nishio | Ekstremalne |
| 11 | Hover, tooltipy, tryb podpowiedzi, eksport SVG | szlif |

Po etapach 1–4 jest działający podgląd dla singli; po 6 — dla większości sudoku z gazet.

---

## 16. Otwarte kwestie

- **Kalibracja wag** — porównać oceny z Sudoku Explainer / HoDoKu na wspólnym zbiorze sudoku.
- **Ograniczenie długości łańcuchów** — AIC i Forcing Chains potrzebują limitu długości (i wagi zależnej od długości), żeby solver był szybki, a ocena sensowna.
- **Format wejścia z kandydatami** dla testów (przykłady z zewnątrz mają już skreślenia).
- **`countAll` przy strategiach** — czy liczyć dostępne ruchy do oceny trudności (koszt wydajności).
- **Wydajność generatora** dla poziomów Ekspert/Ekstremalny — może wymagać hill-climbingu lub puli gotowych sudoku.
- **Hidden Single w linii vs Naked Single** — kolejność i wagi warto potwierdzić na testach z ludźmi.

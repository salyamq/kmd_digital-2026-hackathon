# Mentor review pack — gr_latyshova_short

## Narration

- **L1 hook**: Многие думают, что прибор гамма-метода *посылает* излучение в породу и ловит отражение.  _[no fact]_
- **L2 prediction**: Как думаете: где кривая покажет больше — против глин или против песчаников?  _[no fact]_
- **L3 reveal**: На самом деле прибор ничего не посылает: он *регистрирует* естественное гамма-излучение пород.  _[c1 p.65]_
- **L4 mechanism**: Излучают сами породы: в них рассеяны уран, торий и изотоп калия.  _[c2 p.65]_
- **L5 mechanism**: Самые радиоактивные из осадочных пород — *глины*, поэтому показания связаны с глинистостью.  _[c3 p.65; c4 p.65]_
- **L6 data**: Это реальная кривая скважины Volve. Запись идёт при подъёме прибора — *снизу вверх*.  _[c7 p.64; 15-9-19_SR_COMP.las p.None]_
- **L7 data**: Иззубренность — статистические флуктуации: интерпретируют аномалии, вдвое превышающие их «дорожку».  _[c5 p.65; c6 p.65]_
- **L8 bridge**: Для дата-инженера это признак: относительная амплитуда между двумя опорными пластами. Но опорные пласты выбирают вручную.  _[c9 p.67; c12 p.67; c10 p.67]_
- **L9 transfer**: Проверьте себя: песчаник, а показания высокие. Что вы проверите первым?  _[no fact]_

## Source table

| id | kind | ref | page | status | quote / file |
|---|---|---|---|---|---|
| src1 | reference | М.Г. Латышова. Практическое руководство по интерпретации диаграмм геофизических исследований скважин. 3-е изд. М.: Недра, 1991 |  | reference |  |
| src2 | claim | c1 | 65 | verified | Интенсивность естественного гамма-излучения, регистрируемого прибором, помещенным в изучаемую однородную и безграничную  |
| src3 | claim | c2 | 65 | verified | Их радиоактивность обусловлена наличием весьма малых количеств радиоактивных элементов — урана, тория, актиния, продукто |
| src4 | claim | c3 | 65 | verified | Из всех осадочных пород наиболее радиоактивными являются глины, поэтому величина радиоактивности других, менее активных  |
| src5 | claim | c4 | 65 | verified | Радиоактивность некоторых горных пород осадочного комплекса. |
| src6 | claim | c7 | 64 | verified | регистрация диаграмм осуществляется при движении скважинного снаряда снизу вверх |
| src7 | dataset | Equinor Volve |  | dataset | 15-9-19_SR_COMP.las |
| src8 | claim | c5 | 65 | verified | При непрерывной регистрации на диаграммах радиометрии отмечаются мелкие аномалии (иззубренность), созданные статистическ |
| src9 | claim | c6 | 65 | verified | Интерпретации подлежат аномалии, амплитуды которых не менее чем в два раза превышают ширину "дорожки" статистических флу |
| src10 | claim | c9 | 67 | verified | ΔJγ = ΔI/ΔIоп = (I – Iоп1)/(Iоп2 – Iоп1) |
| src11 | claim | c12 | 67 | verified | просматривается с целью выделения на ней двух опорных пластов |
| src12 | claim | c10 | 67 | verified | Такой способ ручной интерпретации удобен |
| src13 | assumption | Lithology of formations (Åsgard, Draupne/Heather, Hugin, Skagerrak) from NPD lithostratigraphic descriptions, not from the chapter |  | assumption |  |
| src14 | assumption | Formation tops from NPD for well 15/9-19 SR (MD) |  | assumption |  |
| src15 | table | табл. 12 | 65 | verified | Радиоактивность некоторых горных пород осадочного комплекса. |
| src16 | assumption | Lithology of formations from NPD descriptions |  | assumption |  |
| src17 | assumption | Depth window 4282–4362 m chosen to show clay–sand–silt |  | assumption |  |
| src18 | assumption | Reference beds placed at the GR minimum (Hugin) and maximum (Draupne) of this window as an illustration |  | assumption |  |

## Scene specs

### S1 — overlay_card (class A, label data)
- model: `las` 15-9-19_SR_COMP.las GR
- invariants: particles move from the formation TO the instrument (it does not emit); depth increases downward
- assumptions: Lithology of formations (Åsgard, Draupne/Heather, Hugin, Skagerrak) from NPD lithostratigraphic descriptions, not from the chapter; Formation tops from NPD for well 15/9-19 SR (MD)

### S2 — data_chart (class A, label data)
- model: `table`  
- invariants: every value is a cell of Table 12 on p. 65

### S3 — depth_track (class A, label data)
- model: `las` 15-9-19_SR_COMP.las GR
- invariants: recording while the instrument moves bottom -> top (p. 64); curve point depth == instrument depth (one state array)
- assumptions: Lithology of formations from NPD descriptions; Depth window 4282–4362 m chosen to show clay–sand–silt

### S4 — overlay_card (class A, label data)
- model: `las` 15-9-19_SR_COMP.las GR
- invariants: formula (40) from p. 67 shown verbatim
- assumptions: Reference beds placed at the GR minimum (Hugin) and maximum (Draupne) of this window as an illustration

### S5 — question_card (class T, label schematic)

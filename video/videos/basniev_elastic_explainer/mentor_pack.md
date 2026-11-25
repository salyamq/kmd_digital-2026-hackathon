# Mentor review pack — basniev_elastic_explainer

## Narration

- **L1 hook**: Скважину запустили. Кажется, давление сразу падает во всём пласте — будто это бак с водой.  _[no fact]_
- **L2 prediction**: Как думаете: через час после пуска почувствует ли это пласт в километре от скважины? Остановите видео и решите.  _[no fact]_
- **L3 reveal**: На самом деле возмущение давления уходит от скважины *постепенно* — с темпом, который задаёт пьезопроводность пласта.  _[c2 p.None]_
- **L4 mechanism**: Почему так? При упругом режиме сжимаемы и жидкость, и сам пласт.  _[c1 p.None]_
- **L5 mechanism**: Отбор жидкости покрывается тем, что она *расширяется*, а поровый объём пласта уменьшается.  _[c1 p.None]_
- **L6 mechanism**: Поэтому давление подчиняется уравнению пьезопроводности. Его коэффициент *χ* — это проницаемость k, делённая на вязкость μ и упругоёмкость β*.  _[c2 p.None]_
- **L7 mechanism**: А упругоёмкость складывает сжимаемость жидкости, умноженную на пористость, и сжимаемость самого пласта.  _[c3 p.None]_
- **L8 mechanism**: Для скважины с постоянным дебитом в бесконечном пласте есть решение — *основная формула* теории упругого режима.  _[c4 p.None]_
- **L9 mechanism**: Посчитаем её на сетке и посмотрим на пласт сверху. Цвет показывает, на сколько упало давление.  _[no fact]_
- **L10 mechanism**: Возмущение расходится от скважины, и граница заметного падения уходит всё дальше — но *не мгновенно*.  _[c2 p.None]_
- **L11 mechanism**: Справа — профиль давления по радиусу из той же расчётной сетки, поэтому фронт на карте и на графике совпадает.  _[no fact]_
- **L12 mechanism**: Когда r²/(4χt) мало, понижение давления растёт пропорционально *логарифму* времени.  _[c5 p.None]_
- **L13 mechanism**: В логарифмическом масштабе времени это почти *прямая* линия.  _[c5 p.None]_
- **L14 data**: Как это выглядит в реальных данных? Вот забойное давление добывающей скважины месторождения Volve.  _[volve_daily_production.csv p.None]_
- **L15 data**: Скважину остановили — и давление восстанавливается не скачком, а *постепенно*, день за днём. Это и есть кривая восстановления давления.  _[c5 p.None; volve_daily_production.csv p.None]_
- **L16 bridge**: Для дата-инженера картина знакомая: изменение доходит до дальних узлов распределённой системы с задержкой.  _[no fact]_
- **L17 bridge**: А по форме отклика восстанавливают параметры: так по КВД оценивают свойства пласта. Подбор модели к кривой часто до сих пор делают вручную.  _[no fact]_
- **L18 transfer**: Проверьте себя: в пласте две скважины, одну остановили. Когда и как это заметят на второй?  _[no fact]_

## Source table

| id | kind | ref | page | status | quote / file |
|---|---|---|---|---|---|
| src1 | reference | К.С. Басниев, Н.М. Дмитриев, Р.Д. Каневская, В.М. Максимов. Подземная гидромеханика |  | reference |  |
| src2 | claim | c2 |  | no_quote |  |
| src3 | claim | c1 |  | no_quote |  |
| src4 | claim | c3 |  | no_quote |  |
| src5 | claim | c4 |  | no_quote |  |
| src6 | claim | c5 |  | no_quote |  |
| src7 | dataset | Equinor Volve |  | dataset | volve_daily_production.csv |
| src8 | dataset | Equinor Volve |  | dataset | volve_daily_production.csv |
| src9 | formula | Q*mu/(4*pi*k*h) * E1(r**2/(4*chi*t)) |  | no_quote |  |
| src10 | assumption | Q |  | assumption | illustrative rate; replace with the chapter example |
| src11 | assumption | mu |  | assumption | water-like viscosity |
| src12 | assumption | k |  | assumption | 100 mD, typical sandstone |
| src13 | assumption | h |  | assumption | reservoir thickness |
| src14 | assumption | beta |  | assumption | β*, elastic capacity of the reservoir |
| src15 | assumption | dp_min |  | assumption | threshold of a 'noticeable' pressure drop for the front line |
| src16 | assumption | Illustrative parameters (see model params); the chapter gives the formula, not these values |  | assumption |  |
| src17 | formula | Q*mu/(4*pi*k*h) * E1(r**2/(4*chi*t1)) |  | no_quote |  |
| src18 | assumption | t1 |  | assumption | profile time 1 |
| src19 | assumption | t2 |  | assumption | profile time 2 |
| src20 | assumption | t3 |  | assumption | profile time 3 |
| src21 | assumption | Illustrative parameters as in S4; profile times 1 h, 1 day, 10 days chosen for illustration |  | assumption |  |
| src22 | assumption | All parameter values are illustrative (not from the chapter): Q=100 m3/day, μ=1 mPa·s, k=0.1 D, h=10 m, β*=3e-10 1/Pa |  | assumption |  |
| src23 | assumption | Front drawn where Δp = 0.1 bar (display threshold) |  | assumption |  |
| src24 | formula | Q*mu/(4*pi*k*h) * E1(rw**2/(4*chi*t)) |  | no_quote |  |
| src25 | assumption | rw |  | assumption | well radius |
| src26 | assumption | illustrative parameters, see S6 |  | assumption |  |
| src27 | assumption | Daily averages: the build-up is sampled once per day, so the first hours are not resolved |  | assumption |  |

## Scene specs

### S1 — overlay_card (class B, label simulation)
- model: `formula` Q*mu/(4*pi*k*h) * E1(r**2/(4*chi*t)) 
  - Q = 100 m3/сут — {'assumption': True, 'note': 'illustrative rate; replace with the chapter example'}
  - mu = 1 mPa*s — {'assumption': True, 'note': 'water-like viscosity'}
  - k = 0.1 D — {'assumption': True, 'note': '100 mD, typical sandstone'}
  - h = 10 m — {'assumption': True, 'note': 'reservoir thickness'}
  - beta = 3e-10 1/Pa — {'assumption': True, 'note': 'β*, elastic capacity of the reservoir'}
  - dp_min = 0.1 bar — {'assumption': True, 'note': "threshold of a 'noticeable' pressure drop for the front line"}
- invariants: map and profile read the same computed array; pressure drop is largest at the well and decays with distance
- assumptions: Illustrative parameters (see model params); the chapter gives the formula, not these values

### S2 — inset_callouts (class B, label schematic)
- invariants: grains touch (grain-supported framework); fluid only in pores, no free 'lake'

### S3 — overlay_card (class B, label simulation)
- model: `formula` Q*mu/(4*pi*k*h) * E1(r**2/(4*chi*t1)) 
  - Q = 100 m3/сут — {'assumption': True, 'note': 'illustrative rate; replace with the chapter example'}
  - mu = 1 mPa*s — {'assumption': True, 'note': 'water-like viscosity'}
  - k = 0.1 D — {'assumption': True, 'note': '100 mD, typical sandstone'}
  - h = 10 m — {'assumption': True, 'note': 'reservoir thickness'}
  - beta = 3e-10 1/Pa — {'assumption': True, 'note': 'β*, elastic capacity of the reservoir'}
  - dp_min = 0.1 bar — {'assumption': True, 'note': "threshold of a 'noticeable' pressure drop for the front line"}
  - t1 = 1 hour — {'assumption': True, 'note': 'profile time 1'}
  - t2 = 1 day — {'assumption': True, 'note': 'profile time 2'}
  - t3 = 10 day — {'assumption': True, 'note': 'profile time 3'}
- invariants: the three profiles come from one formula (c4) with the same parameters as S1/S4; later profiles reach farther: the disturbance spreads, it does not appear everywhere at once
- assumptions: Illustrative parameters as in S4; profile times 1 h, 1 day, 10 days chosen for illustration

### S4 — field_evolution (class B, label simulation)
- model: `formula` Q*mu/(4*pi*k*h) * E1(r**2/(4*chi*t)) 
  - Q = 100 m3/сут — {'assumption': True, 'note': 'illustrative rate; replace with the chapter example'}
  - mu = 1 mPa*s — {'assumption': True, 'note': 'water-like viscosity'}
  - k = 0.1 D — {'assumption': True, 'note': '100 mD, typical sandstone'}
  - h = 10 m — {'assumption': True, 'note': 'reservoir thickness'}
  - beta = 3e-10 1/Pa — {'assumption': True, 'note': 'β*, elastic capacity of the reservoir'}
  - dp_min = 0.1 bar — {'assumption': True, 'note': "threshold of a 'noticeable' pressure drop for the front line"}
- invariants: map and profile read the same array; same formula and parameters as S1/S3
- assumptions: All parameter values are illustrative (not from the chapter): Q=100 m3/day, μ=1 mPa·s, k=0.1 D, h=10 m, β*=3e-10 1/Pa; Front drawn where Δp = 0.1 bar (display threshold)

### S5 — data_chart (class B, label simulation)
- model: `formula` Q*mu/(4*pi*k*h) * E1(rw**2/(4*chi*t)) 
  - Q = 100 m3/сут — {'assumption': True, 'note': 'same as S6'}
  - mu = 1 mPa*s — {'assumption': True, 'note': 'same as S6'}
  - k = 0.1 D — {'assumption': True, 'note': 'same as S6'}
  - h = 10 m — {'assumption': True, 'note': 'same as S6'}
  - beta = 3e-10 1/Pa — {'assumption': True, 'note': 'same as S6'}
  - rw = 0.1 m — {'assumption': True, 'note': 'well radius'}
- invariants: same formula and parameters as S4
- assumptions: illustrative parameters, see S6

### S6 — data_chart (class A, label data)
- model: `csv` volve_daily_production.csv 
- invariants: shut-in band derived from the data (ON_STREAM_HRS == 0), not drawn by hand
- assumptions: Daily averages: the build-up is sampled once per day, so the first hours are not resolved

### S7 — overlay_card (class A, label data)
- model: `csv` volve_daily_production.csv 
- invariants: same Volve data as S6

### S8 — question_card (class T, label schematic)

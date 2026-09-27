# rank-momentum/scripts

`kr.json`·`us.json`(가격/모멘텀 데이터)과 `kr-history.json`·`us-history.json`
(기준일 재계산용 15개월 종가 히스토리)을 갱신하는 스크립트 모음.

## 배경 — 왜 이 README가 있는가

이 6개 스크립트 중 4개(`refresh_kr_prices.py`·`refresh_us_prices.py`·
`update_kr_history_incremental.py`·`update_us_history_incremental.py`)는
2026-09-24에 작성되어 실제로 그날 `kr.json`/`us.json` 갱신에 쓰였지만,
**한 번도 이 저장소에 커밋되지 않고 세션 스크래치패드(`/private/tmp/...`)에만
존재**했다. 2026-09-28 데이터 갱신 요청 때 스크래치패드가 아직 살아있어
회수했지만, 스크래치패드는 세션이 끝나면 사라지는 임시 공간이라 다음에는
이런 행운이 없을 수 있다 — 그래서 이번에 정식 커밋한다.

`kr.json`/`us.json`을 **처음부터** 만드는 생성기(유니버스 선정·WICS 섹터
매핑·테마 추출·US 유니버스 수집)는 이번에도 찾지 못했다 — 아래
["여전히 없는 것"](#여전히-없는-것-복원-실패) 참고. 이 스크립트들은 **기존
kr.json/us.json이 있다는 전제 하에 가격·수익률·점수만 새로고침**한다.

## 스크립트 역할

| 스크립트 | 역할 | 건드리는 파일 |
|---|---|---|
| `refresh_kr_prices.py` | KR 671종목 가격·수익률(`ret_*`·`pct_*`)·`gap_52w_high`·`mom_score`/`price_score`/`combined` 재계산. sector/industry/themes/per/pbr/marcap/수급 등 정적 필드는 그대로 보존 | `data/kr.json` (in-place) |
| `refresh_us_prices.py` | US 3,559종목 동일 작업 | `data/us.json` (in-place) |
| `update_kr_history_incremental.py` | `kr-history.json`(기준일 모드용 15개월 종가)에 최근 10일 중 없는 거래일만 증분 추가 | `data/kr-history.json` (in-place) |
| `update_us_history_incremental.py` | 동 US 버전 | `data/us-history.json` (in-place) |
| `fetch_kr_history.py`(기존) | kr-history.json **전체 재구축**(15개월치 처음부터) — 증분이 아니라 풀 리빌드 | `data/kr-history.json` |
| `fetch_us_history.py`(기존) | 동 US 전체 재구축 | `data/us-history.json` |
| `fetch_us_valuation.py`(기존) | US 밸류에이션(PER/ROE 등) 증분 백필 | `data/us.json` |
| `validate_history.py`(기존) | history 파일이 kr.json/us.json의 수익률을 정확히 재현하는지 검증 | 읽기 전용 |

## 실행 순서 (주간/일 단위 가격 갱신)

```bash
cd rank-momentum/scripts
~/.venv-trading/bin/python3 refresh_kr_prices.py
~/.venv-trading/bin/python3 refresh_us_prices.py
~/.venv-trading/bin/python3 update_kr_history_incremental.py
~/.venv-trading/bin/python3 update_us_history_incremental.py
python3 validate_history.py   # 선택 — history와 스냅샷 일치 재검산
```

**실행 전 반드시 `data/kr.json`·`data/us.json`·`data/kr-history.json`·
`data/us-history.json`을 백업**해라(스크립트가 in-place로 덮어쓴다). 실행 후
정적 필드 채움률이 실행 전과 같은지 확인해라(아래 게이트가 자동으로
막아주지만, 이중 확인 권장).

## 외부 의존

- **yfinance**(`~/.venv-trading/bin/python3`에 설치돼 있음, pandas·numpy 동반) — 4개 스크립트 모두 이것만 쓴다. **tossctl·k-dart 세션은 필요 없다**
  (수급·재무 필드는 정적 필드로 취급되어 이 스크립트들이 건드리지 않는다 —
  그 필드들을 갱신하려면 `sec-brain/src/comp-kr/fetch_comp_raw.py`의
  `fetch_flows_data`/`fetch_dart_data` 계열을 참고해야 하는데, 그 스크립트는
  KOSPI 200개 한정이라 671종목 전체에는 그대로 못 쓴다 — 마찬가지로
  ["여전히 없는 것"](#여전히-없는-것-복원-실패) 참고).
- 실행 시간: KR 671종목 ~1~2분, US 3,559종목 ~3~5분(배치 다운로드, `time.sleep`
  레이트리밋 있음). foreground + `gtimeout`으로 돌릴 것 — 백그라운드로 던지고
  기다리지 말 것(장시간 작업 중 hang 오판·이중 실행 방지, 과거 재발 사고).
- 룩백은 전부 **달력 기준**(거래일 인덱스 아님) — `cal_return(series, weeks)`가
  `as_of − 7×weeks일` 이하 마지막 종가를 찾는다. 트레이딩일 인덱스 산술
  (`iloc[-61]` 류)로 되돌리면 과거에 46pp 오차(가온전선 무상증자) 재발 이력이
  있다.

## 알려진 사고 — 재발 방지 가드

1. **`industry` 소실**(2026-09-22 재발): 과거 `refresh_kr_prices.py`가
   `industry=None`인 kr.json을 그대로 복사해 필드가 비었던 적이 있다(원인은
   업스트림에서 kr.json 자체가 이미 비어있었던 것 — 이 스크립트 자체는
   `dict(s)`로 기존 필드를 전부 복사하므로 정적 필드를 스스로 지우지는
   않는다). 이번 버전은 실행 전후 정적 필드 개수를 비교해 **하나라도
   줄어들면 저장을 중단하는 게이트**(`STATIC_FIELDS` no-regression check)를
   추가했다 — sector·industry·themes·per·pbr·marcap(US는 marcap_usd)·
   inst_net_20d·for_net_20d.
2. **`Infinity`/`NaN`이 JSON에 들어감**(과거 PER=Infinity로 `JSON.parse` 깨짐):
   이번 버전은 저장 직전 `_sanitize()`로 모든 float을 `math.isfinite()` 검사해
   비정상값을 `null`로 치환하고, `json.dump(..., allow_nan=False)`를 이중
   안전장치로 걸었다 — 혹시 sanitize를 빠져나간 값이 있으면 조용히 깨진
   JSON을 쓰는 대신 예외로 죽는다.
3. **pykrx vs yfinance 수정주가 불일치**(46pp, 가온전선 무상증자): `kr.json`과
   `kr-history.json`은 반드시 **같은 소스**(yfinance `auto_adjust=True`)를
   써야 한다. 이 4개 스크립트는 모두 yfinance로 통일돼 있다 — pykrx로 되돌리지
   말 것.

## 여전히 없는 것 (복원 실패 — 명시)

아래는 이번에도 스크래치패드·transcript·comp-kr 어디서도 찾지 못했다.
**종목 구성이 바뀌면**(신규상장·상장폐지·유니버스 재정의) 이 부분들을
처음부터 다시 만들어야 하는데, 그 코드가 없다:

- **KR 유니버스 쿼리**(KOSPI+KOSDAQ 시총 3,000억+ → 671종목 선정 로직).
  결과 사실("KOSPI 399 + KOSDAQ 276")만 커밋 메시지에 남아있다.
- **US 유니버스 수집**(시총 $217M+ · 20일 평균거래대금 $1M+ → 3,559종목).
  코드 흔적이 전혀 없다.
- **WICS sector/industry 매핑**: "Naver upJongName → WICS 10섹터 매핑,
  신규 473종목은 detail API upJongName으로 파생"이라는 방법론만 커밋
  메시지에 남아있고 실제 매핑 로직은 없다. `sec-brain/src/comp-kr/data/
  wics_map.json`·`sectors.json`이 있지만 **KOSPI200(200종목) 스코프라
  671종목의 1/3도 안 커버**하고 KOSDAQ은 전무하다.
- **테마 추출**("Naver 테마 시스템, 테마당 median 3종목"): 알고리즘 없음.
- **US 밸류에이션 외 정적 필드의 원 출처**: `per`/`pbr`가 어느 API에서 왔는지
  (DART가 아님 — `fetch_comp_raw.py`의 DART 경로는 `trailing_per`를
  명시적으로 NaN 처리) 확인 안 됨. `fetch_us_valuation.py`(기존, 이 저장소에
  커밋되어 있음)가 US의 `per`/`forward_per`/`roe`/`earnings_growth`
  증분 백필은 하지만, **최초 값이 어떻게 채워졌는지**는 별개 문제.

이 부분이 필요해지면(신규 상장 반영 등) 반드시 사용자에게 유니버스 기준·
WICS 매핑 방식·PER 소스를 다시 확인받고 새로 설계해야 한다 — 추측으로
채우지 말 것.

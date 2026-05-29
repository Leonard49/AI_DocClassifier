**Changes_20260527**

**1\. Parallel pipeline (main\_v6.py)**

*   **Phase A**: Read documents in parallel (READ\_WORKERS = 4)
*   **Phase B**: Classify in parallel (CLASSIFY\_WORKERS = 4)
*   **Phase C**: Copy / tag **serially** (safer for Feishu writes)

**2\. Classification (QwenAI\_new.py + classify\_cache.py)**

*   Shorter input: **title + first 3000 chars** (CLASSIFY\_MAX\_CHARS)
*   **SQLite cache** (classify\_cache.db) keyed by obj\_token + content hash — reruns skip LLM calls
*   CLASSIFY\_VERBOSE = False reduces log noise in batch runs

**3\. Folder API (FeishuTitleCheck.py)**

*   **In-memory cache** of direct children per parent
*   check\_duplicate returns node\_token directly — removed slow BFS via FindNodeByName
*   \_ensure\_child\_folder helper invalidates cache after creating nodes

**Tunable settings (top of main\_v6.py)**

**Setting**

**Default**

**Notes**

READ\_WORKERS

4

Increase if Feishu read rate allows

CLASSIFY\_WORKERS

4

Lower if you hit Qwen rate limits

CLASSIFY\_MAX\_CHARS

3000

Raise if accuracy drops

USE\_CLASSIFY\_CACHE

True

Disable to force re-classify

**Expected impact**

*   **~3–4×** faster classification phase (parallel workers)
*   **Much faster** reruns (classification cache)
*   **Fewer wiki API calls** per document (child list cache + no BFS)

Run as before: python main\_v6.py. If the API returns 429 errors, reduce CLASSIFY\_WORKERS to 2

**Issues Improve**

1.  **HTTP 400 Error**

**Root cause**

The HTTP **400** is almost always **Feishu rate limiting**, not a bad document ID.

The raw\_content API allows **at most 5 requests per second per app**. Over-limit responses look like:

*   HTTP **400**
*   code: **99991400**
*   msg: request trigger frequency limit

After adding parallel reads (READ\_WORKERS = 4), many requests fired at once, so most failed with 400 Client Error while raise\_for\_status() hid the real error code.

A single-document call works; a burst of parallel calls reproduces the failure.

**What we changed**

1.  **feishu\_rate\_limit.py** – global limiter at **4 requests/second** (under the 5/s cap).
2.  **ReadFeishuRaw.py** – uses the limiter on every read; **retries with backoff** on 99991400; prints Feishu code / msg instead of only “400”.
3.  **main\_v6.py** – passes wiki\_node\_token for fallback resolution; READ\_WORKERS = 3.

Verified: **10/10** documents read successfully with 3 parallel workers + rate limiting.

1.  **Gateway 502 Error**

**Cause**

The 502 Bad Gateway comes from your **LiteLLM gateway** (qlitellm.phicotek.com), not from Feishu.

Your log shows **4 parallel** POST /chat/completions calls hitting 502 at the same time (e.g. 11:41:26). The gateway is overloaded; the OpenAI SDK’s built-in retry (~0.4s) makes several workers retry together, which often makes it worse.

**What we changed**

1.  **llm\_rate\_limit.py** – at most **2 concurrent** LLM calls and ~**1.2 requests/second**
2.  **QwenAI\_new.py** – SDK max\_retries=0; custom retries with **exponential backoff** (up to ~45s) for 502/503/429/5xx
3.  **main\_v6.py** – CLASSIFY\_WORKERS reduced **4 → 2**; LLM\_MAX\_RETRIES = 6
4.  On final failure, classification returns **None** (skip document) instead of wrongly labeling as Others

You’ll see messages like:

⏳ LLM 暂时不可用 (HTTP 502)，2.3s 后重试 (1/6)

**Tuning (if 502 still appears)**

**Setting**

**Location**

**Suggestion**

CLASSIFY\_WORKERS

main\_v6.py

Try 1

LLM\_RATE\_LIMITER

llm\_rate\_limit.py

Lower to 0.8 req/s

LLM\_CONCURRENCY

llm\_rate\_limit.py

Set to 1

Re-run python main\_v6.py; cached classifications are reused and won’t call the API again.

**Note:** 502 is a **server-side** issue on the LiteLLM host. These changes reduce how hard you hit it; if it persists, contact whoever runs qlitellm.phicotek.com or run classification during off-peak hours.


**Changes_20260529**
**1. has_body_content() in main_v6.py**

Treats content as empty when it’s None, "", or only whitespace. Title is ignored.

**2. Read phase (ReadFeishuRaw.py)**

Whitespace-only API responses are treated as no content (None), same as a failed read.

**3. Classify phase (QwenAI_new.py)**

Previously, empty body + non-empty title still triggered AI classification (title-only).

Now: if body is empty → return None, no LLM call.

**4. Copy/tag phase (main_v6.py)**

Empty-body docs are counted as skipped, not failed:

⏭️ 正文为空，跳过（不论标题）: Some Document Title

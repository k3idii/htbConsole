import httpx
import asyncio
import json
import os
import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


class TokenExpiredError(Exception):
    pass


_burp_addr = os.environ.get("USE_BURP")
burp_proxy = httpx.Proxy(_burp_addr) if _burp_addr else None


def _maybe_int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return s


class HTBSession:
  """Framework-agnostic HTB API session: client mgmt, generic request, logging.

  No dependency on any UI. Logging goes through :meth:`_handle_log_event` /
  :meth:`_handle_log_debug` / :meth:`_handle_notify`, which are no-ops by default
  and meant to be overridden by subclasses to wire in a UI or logger.
  The cache file path is taken from the constructor (``cache_file``).
  """

  base_url = ""
  headers = {
      "Accept": "application/json, text/plain, */*",
  }

  REQUEST_TIMEOUT = 15
  DOWNLOAD_TIMEOUT = 60
  USE_CACHE = True # jsut in case you want to globally disable that 

  def __init__(self, token: str, cache_file: str = None) -> None:
    self.token = token
    self.headers = dict(self.headers)
    self.headers["Authorization"] = f"Bearer {token}"
    self._client = None

    # request cache (opt-in out USE_CACHE and cache_this kwarg)
    self.CACHE = {}
    self._CACHE_FILE = cache_file or self.CACHE_FILE_NAME
    self.try_load_cache()

    self._token_dead = False

  # --- logging hooks (override to integrate with a UI / logger) -------------

  def _handle_log_event(self, message):
    """A user-facing event. Override to display / log."""

  def _handle_log_debug(self, message, *args, **kwargs):
    """A debug trace. Override to display / log."""

  def _handle_notify(self, message, severity="information", timeout=5):
    """A user notification. Override to display."""

  # --- client management ----------------------------------------------------

  def _build_client_kw(self):
    kw = {"verify": False}
    if burp_proxy:
      kw["proxy"] = burp_proxy
    return kw

  async def _get_client(self):
    if self._client is None or self._client.is_closed:
      self._client = httpx.AsyncClient(**self._build_client_kw())
    return self._client

  async def close(self):
    if self._client and not self._client.is_closed:
      await self._client.aclose()
      self._client = None

  def _make_url(self, endpoint):
    return f"{self.base_url}{endpoint}"

  async def _send(self, method, url, **kw):
    client = await self._get_client()
    return await client.request(method=method, url=url, headers=self.headers, **kw)

  @staticmethod
  def _error_message(response):
    try:
      return response.json().get("message", response.text[:400])
    except Exception:
      return response.text[:400]

  # --- request cache --------------------------------------------------------

  def is_in_cache(self, req_id):
    return req_id in self.CACHE

  def get_from_cache(self, req_id):
    return self.CACHE.get(req_id, None)

  def try_load_cache(self):
    if self._CACHE_FILE is None:
        return
    try:
      self.CACHE = json.load(open(self._CACHE_FILE))
    except Exception as ex:
      self._handle_log_debug(f"API::CACHE LOAD FAILED : {ex}")

  def save_to_cache(self, req_id, data):
    self.CACHE[req_id] = data
    if self._CACHE_FILE is None:
        return
    json.dump(self.CACHE, open(self._CACHE_FILE, "w"))
    self._handle_log_debug("API::CACHE SAVED", req_id)

  # --- dont_cache decorator (yes, can be both a classmethod)
  # usage :
  # @self.dont_cache
  def dont_cache(self, func):
    def wrapper(*args, **kwargs):
      kwargs["cache_this"] = 0
      return func(*args, **kwargs)
    return wrapper

  # --- generic requests -----------------------------------------------------

  async def async_get(self, endpoint:str, **kw):
    return await self.make_async_request(
      method = "GET",
      endpoint = endpoint,
      **kw
    )

  async def async_post(self, endpoint:str, data:dict, **kw):
    return await self.make_async_request(
      method = "POST",
      endpoint = endpoint,
      json = data,
      cache_this = 0,
      **kw
    )

  def do_get(self, endpoint:str,**kw):
    return self.make_sync_request(
      method = "GET",
      endpoint = endpoint,
      **kw
    )

  def do_post(self, endpoint:str, data:dict, **kw):
    return self.make_sync_request(
      method = "POST",
      endpoint = endpoint,
      json = data,
      cache_this=0,
      **kw
    )

  def make_sync_request(self, method, endpoint, **kw):
    try:
      loop = asyncio.get_running_loop()
    except RuntimeError:
      loop = None
    if loop and loop.is_running():
      import concurrent.futures
      with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, self.make_async_request(method, endpoint, **kw)).result()
    return asyncio.run(
      self.make_async_request(
        method,
        endpoint,
        **kw
      )
    )

  async def make_async_request(self, method="GET", endpoint="/",  cache_this=1, **kw):
    if self._token_dead:
      raise TokenExpiredError("HTB API marked as dead. check !")

    URL = self._make_url(endpoint)
    req_id = f"{method}_{endpoint}_{str(kw)}"
    self._handle_log_debug(f"API::REQUEST {method} > {URL}", **kw)

    if self.USE_CACHE and cache_this:
      data = self.get_from_cache(req_id)
      if data is not None:
        self._handle_log_debug(f"API::CACHED {method} > {URL}", str(data))
        return data 

    # not in cache or don't cache  -> fetch 

    kw.setdefault("timeout", self.REQUEST_TIMEOUT)
    response = await self._send(method, URL, **kw)
    if response.status_code == 401:
      self._token_dead = True
      self._handle_log_event("API::TOKEN EXPIRED or INVALID — update HTB_TOKEN and restart")
      self._handle_notify("Token expired or invalid. Update HTB_TOKEN and restart.", severity="error", timeout=10)
      raise TokenExpiredError(f"HTB API token is expired or invalid (response : {response.status_code} : {self._error_message(response)})")

    if response.status_code not in (200, 201):
      raise Exception(f"Request {method} to {URL} fail with {response.status_code}: {self._error_message(response)}")
    
    data = response.json()
    self._handle_log_debug(f"API::RESULT {method}", response, str(data))
    
    if self.USE_CACHE and cache_this:
      self.save_to_cache(req_id, data)
    
    return data

  async def download_bytes(self, endpoint):
    r = await self._send("GET", self._make_url(endpoint), timeout=self.DOWNLOAD_TIMEOUT, follow_redirects=True)
    if r.status_code == 401:
      self._token_dead = True
      raise TokenExpiredError("HTB API token is expired or invalid")
    if r.status_code != 200:
      raise Exception(f"Download {r.status_code}: {endpoint}")
    return r.content


class HTBApiSession(HTBSession):
  base_url = "https://labs.hackthebox.com"
  headers = {
      "Accept": "application/json, text/plain, */*",
      "User-Agent": "HTBClient/1.0.0",
  }

  # --- named API calls ------------------------------------------------------
  # every HTB API endpoint used by the app lives here; callers never build URLs.

  # account / profile
  async def api_htb_user_info(self, params=None, **kw):
    return await self.async_get("/api/v4/user/info", params=params, **kw)

  async def api_htb_profile(self, uid, params=None, **kw):
    return await self.async_get(f"/api/v4/profile/{uid}", params=params, **kw)

  async def api4_htb_profile_activity(self, uid, params=None, **kw):
    return await self.async_get(f"/api/v4/profile/activity/{uid}", params=params, **kw)

  async def api_htb_profile_activity(self, uid, params=None, **kw):
    #api/v5/user/profile/activity/41118?page=1
    # add page=1 to params
    if params is None:
        params = {}
    params["page"] = 1
    return await self.async_get(f"/api/v5/user/profile/activity/{uid}", params=params, **kw)

  # challenges
  async def api_htb_chal_list(self, params=None, **kw):
    return await self.async_get("/api/v4/challenges", params=params, **kw)

  async def api_htb_chal_info(self, chal_id, params=None, **kw):
    return await self.async_get(f"/api/v4/challenge/info/{chal_id}", params=params, **kw)

  async def api_htb_chal_categories(self, params=None, **kw):
    return await self.async_get("/api/v4/challenge/categories/list", params=params, **kw)

  async def api_htb_chal_writeup(self, chal_id, params=None, **kw):
    return await self.async_get(f"/api/v4/challenge/{chal_id}/writeup", params=params, **kw)

  async def api_htb_chal_writeup_official(self, chal_id, params=None, **kw):
    return await self.async_get(f"/api/v4/challenge/{chal_id}/writeup/official", params=params, **kw)

  async def api_htb_chal_download_link(self, chal_id, params=None, **kw):
    return await self.async_get(f"/api/v4/challenges/{chal_id}/download_link", params=params, **kw)

  async def api_htb_chal_start(self, chal_id, **kw):
    return await self.async_post("/api/v4/container/start", {"containerable_id": _maybe_int(chal_id)}, **kw)

  async def api_htb_chal_stop(self, chal_id, **kw):
    return await self.async_post("/api/v4/container/stop", {"containerable_id": _maybe_int(chal_id)}, **kw)

  async def api_htb_chal_submit(self, chal_id, flag, **kw):
    return await self.async_post("/api/v4/challenge/own", {"challenge_id": _maybe_int(chal_id), "flag": flag}, **kw)

  # sherlocks
  async def api_htb_sherlock_list(self, params=None, **kw):
    return await self.async_get("/api/v4/sherlocks", params=params, **kw)

  async def api_htb_sherlock_get(self, sherlock_id, params=None, **kw):
    return await self.async_get(f"/api/v4/sherlocks/{sherlock_id}", params=params, **kw)

  async def api_htb_sherlock_info(self, sherlock_id, params=None, **kw):
    return await self.async_get(f"/api/v4/sherlocks/{sherlock_id}/info", params=params, **kw)

  async def api_htb_sherlock_tasks(self, sherlock_id, params=None, **kw):
    return await self.async_get(f"/api/v4/sherlocks/{sherlock_id}/tasks", params=params, **kw)

  async def api_htb_sherlock_download_link(self, sherlock_id, params=None, **kw):
    return await self.async_get(f"/api/v4/sherlocks/{sherlock_id}/download_link", params=params, **kw)

  async def api_htb_sherlock_submit(self, sherlock_id, task_id, answer, **kw):
    return await self.async_post(f"/api/v4/sherlocks/{sherlock_id}/tasks/{task_id}/flag", {"flag": answer}, **kw)

  # machines
  async def api_htb_machine_list(self, params=None, **kw):
    return await self.async_get("/api/v4/machine/paginated", params=params, **kw)

  async def api_htb_machine_retired(self, params=None, **kw):
    return await self.async_get("/api/v4/machine/list/retired/paginated", params=params, **kw)

  async def api_htb_machine_active(self, params=None, **kw):
    kw.setdefault("cache_this", 0)
    return await self.async_get("/api/v4/machine/active", params=params, **kw)

  async def api_htb_machine_profile(self, name, params=None, **kw):
    return await self.async_get(f"/api/v4/machine/profile/{name}", params=params, **kw)

  async def api_htb_machine_submit(self, machine_id, flag, **kw):
    return await self.async_post("/api/v5/machine/own", {"id": _maybe_int(machine_id), "flag": flag}, **kw)

  # machine / arena lifecycle
  async def api_htb_vm_spawn(self, machine_id, **kw):
    return await self.async_post("/api/v4/vm/spawn", {"machine_id": _maybe_int(machine_id)}, **kw)

  async def api_htb_vm_terminate(self, machine_id, **kw):
    return await self.async_post("/api/v4/vm/terminate", {"machine_id": _maybe_int(machine_id)}, **kw)

  async def api_htb_vm_reset(self, machine_id, **kw):
    return await self.async_post("/api/v4/vm/reset", {"machine_id": _maybe_int(machine_id)}, **kw)

  async def api_htb_arena_start(self, **kw):
    return await self.async_post("/api/v4/arena/start", {}, **kw)

  async def api_htb_arena_stop(self, **kw):
    return await self.async_post("/api/v4/arena/stop", {}, **kw)

  async def api_htb_arena_reset(self, **kw):
    return await self.async_post("/api/v4/arena/reset", {}, **kw)

  async def api_htb_arena_submit(self, flag, **kw):
    return await self.async_post("/api/v4/arena/own", {"flag": flag}, **kw)

  # season / connection
  async def api_htb_season_list(self, params=None, **kw):
    return await self.async_get("/api/v4/season/list", params=params, **kw)

  async def api_htb_season_user_rank(self, season_id, params=None, **kw):
    return await self.async_get(f"/api/v4/season/user/rank/{season_id}", params=params, **kw)

  async def api_htb_connection_status(self, params=None, **kw):
    kw.setdefault("cache_this", 0)
    return await self.async_get("/api/v4/connection/status", params=params, **kw)

  async def api_htb_connections_servers(self, params=None, **kw):
    return await self.async_get("/api/v4/connections/servers", params=params, **kw)


class HTBCTFSession(HTBSession):

  base_url = "https://ctf.hackthebox.com"
  headers = {
      "Accept": "application/json",
  }

  # --- named API calls ------------------------------------------------------

  async def api_ctf_list(self, params=None, **kw):
    return await self.async_get("/api/ctfs", params=params, **kw)

  async def api_ctf_past(self, params=None, **kw):
    return await self.async_get("/api/ctfs/past", params=params, **kw)

  async def api_ctf_info(self, ctf_id, params=None, **kw):
    return await self.async_get(f"/api/ctfs/{ctf_id}", params=params, **kw)

  async def api_ctf_scores(self, ctf_id, params=None, **kw):
    return await self.async_get(f"/api/ctfs/scores/{ctf_id}", params=params, **kw)

  async def api_ctf_download(self, chall_id):
    return await self.download_bytes(f"/api/challenges/{chall_id}/download")

  async def api_ctf_submit(self, task_id, flag, extra=None):
    body = {"challenge_id": _maybe_int(task_id), "flag": flag}
    if extra:
      body.update(extra)
    return await self.async_post("/api/flags", body)

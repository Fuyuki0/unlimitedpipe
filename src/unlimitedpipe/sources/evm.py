"""On-chain events from Ethereum and Base, read from public JSON-RPC endpoints: Aave lending
utilization and liquidations, big stablecoin transfers, and new Uniswap pools with money in
them."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, Literal

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event
from unlimitedpipe.state import state_path, write_json_atomic

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
LIQUIDATION = "0xe413a321e8681d831f4dbccbca790d2952b56f977908e45be37335533e005286"  # Aave V3
POOL_CREATED = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"  # Uniswap V3
PAIR_CREATED = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"  # Uniswap V2
ZERO = "0x" + "0" * 40

CHAINS: dict[str, dict[str, Any]] = {
    "ethereum": {
        "name": "Ethereum",
        "rpc": "https://ethereum-rpc.publicnode.com",
        "env": "ETHEREUM_RPC_URL",
        "explorer": "https://etherscan.io",
        "block_seconds": 12,
        "aave_pool": "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2",
        "aave_data": "0x7b4eb56e7cd4b454ba8ff71e4518426369a138a3",
        "aave_oracle": "0x54586be62e3c3580375ae3723c145253060ca0c2",
        "uniswap_v3": "0x1f98431c8ad98523631ae4a59f267346ea31f984",
        "uniswap_v2": "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f",
        "tokens": {  # symbol: (address, decimals)
            "WETH": ("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", 18),
            "USDC": ("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6),
            "USDT": ("0xdac17f958d2ee523a2206206994597c13d831ec7", 6),
            "WBTC": ("0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", 8),
            "wstETH": ("0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0", 18),
            "cbBTC": ("0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf", 8),
            "USDe": ("0x4c9edd5852cd905f086c759e8383e09bff1e68b3", 18),
        },
        "stablecoins": ["USDT", "USDC"],
    },
    "base": {
        "name": "Base",
        "rpc": "https://base-rpc.publicnode.com",
        "env": "BASE_RPC_URL",
        "explorer": "https://basescan.org",
        "block_seconds": 2,
        "aave_pool": "0xa238dd80c259a72e81d7e4664a9801593f98d1c5",
        "aave_data": "0xd82a47fdebb5bf5329b09441c3dab4b5df2153ad",
        "aave_oracle": "0x2cc0fc26ed4563a5ce5e8bdcfe1a2878676ae156",
        "tokens": {
            "WETH": ("0x4200000000000000000000000000000000000006", 18),
            "USDC": ("0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", 6),
            "cbBTC": ("0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf", 8),
            "wstETH": ("0xc1cba3fcea344f92d9239c08c0568f6f2f0ee452", 18),
            "cbETH": ("0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22", 18),
        },
        "stablecoins": ["USDC"],
    },
}
MAX_RANGE = 1000  # blocks per eth_getLogs: public endpoints refuse more
KEEP_UP = 20  # read at most this many ranges a run; further behind, skip ahead
LAG = 2  # the newest blocks are not always indexed yet
PENDING_HOURS = 24  # how long a new pool may take to get money in before it is dropped


def word(data: str, n: int) -> int:
    """The n-th 32-byte word of ABI-encoded hex data, as a number."""
    data = data.removeprefix("0x")
    return int(data[n * 64 : (n + 1) * 64] or "0", 16)


def word_hex(data: str, n: int) -> str:
    return data.removeprefix("0x")[n * 64 : (n + 1) * 64]


def address_of(topic_or_word: str) -> str:
    return "0x" + topic_or_word.removeprefix("0x")[-40:].lower()


def text_of(result: str) -> str:
    """An ABI-encoded string (or a bytes32 name, as some old tokens return)."""
    data = result.removeprefix("0x")
    if len(data) == 64:
        return bytes.fromhex(data).rstrip(b"\0").decode("utf-8", "replace")
    try:
        start = int(data[:64], 16) * 2
        length = int(data[start : start + 64], 16)
        raw = bytes.fromhex(data[start + 64 : start + 64 + length * 2])
        return raw.decode("utf-8", "replace").strip()
    except ValueError:
        return ""


def short_address(address: str) -> str:
    return f"{address[:6]}…{address[-4:]}"


def utilization(result: str) -> dict[str, float]:
    """Aave's getReserveData: supplied, borrowed, and the yearly rates (rays, APR)."""
    supplied, stable, variable = word(result, 2), word(result, 3), word(result, 4)
    borrowed = stable + variable
    return {
        "utilization": borrowed / supplied if supplied else 0.0,
        "supplied": supplied,
        "borrowed": borrowed,
        "supply_rate": word(result, 5) / 1e27,
        "borrow_rate": word(result, 6) / 1e27,
    }


class Evm(Source):
    """On-chain events from Ethereum and Base, from public JSON-RPC endpoints.

    `aave` lists Aave V3 markets whose utilization (borrowed over supplied) is at least
    --min-utilization: near 100%, lenders cannot withdraw and borrowing costs jump.
    `liquidations` lists Aave V3 liquidations of at least --min-value dollars, priced by Aave's
    own oracle. `transfers` lists stablecoin transfers (USDT, USDC) of at least --min-value
    dollars, mints and burns included. `new-pools` lists new Uniswap V2 and V3 pools of a token
    against WETH, USDC or USDT once at least --min-value dollars of those are in them (most new
    pools never get any). Endpoints: public ones by default; set $ETHEREUM_RPC_URL or
    $BASE_RPC_URL (e.g. a free Alchemy URL, which stays out of outputs) for your own.
    """

    name = "evm"
    examples = (
        "unlimited evm aave --chain ethereum",
        "unlimited evm liquidations --chain base --min-value 100000",
        "unlimited evm transfers --min-value 50000000",
        "unlimited evm new-pools --min-value 100000",
    )

    resource: Literal["aave", "liquidations", "transfers", "new-pools"] = arg("What to read")
    chain: Literal["ethereum", "base"] = opt("Which chain", default="ethereum")
    min_value: float = opt(
        "Dollars: liquidations (default 100,000), transfers (25,000,000), new pools' money "
        "(100,000)",
        default=0.0,
    )
    min_utilization: float = opt("aave: only markets at least this used (0 to 1)", default=0.9)
    namespace: str | None = opt(
        "Name of the state that remembers the last block read", default=None
    )
    timeout: float = opt("Seconds to wait for each request", default=30.0)

    def __post_init__(self) -> None:
        if self.resource == "new-pools" and self.chain != "ethereum":
            raise ValueError("new-pools reads Ethereum's Uniswap only, for now")
        if not 0 <= self.min_utilization <= 1:
            raise ValueError("--min-utilization is a share, 0 to 1 (0.9 is 90%)")
        defaults = {"liquidations": 100_000, "transfers": 25_000_000, "new-pools": 100_000}
        self._min = self.min_value or defaults.get(self.resource, 0)
        self._chain = CHAINS[self.chain]
        self._url = os.environ.get(self._chain["env"]) or self._chain["rpc"]

    async def _rpc(self, ctx: Context, method: str, params: list[Any]) -> Any:
        response = await ctx.http.post(
            self._url,
            json_body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=self.timeout,
            secret_url=True,  # a URL with a key in it stays out of messages
        )
        answer = json.loads(response.text)
        if "error" in answer:
            raise ValueError(f"{method}: {answer['error'].get('message', answer['error'])}")
        return answer["result"]

    async def _call(self, ctx: Context, to: str, data: str) -> str:
        return await self._rpc(ctx, "eth_call", [{"to": to, "data": data}, "latest"])

    async def _price(self, ctx: Context, token: str) -> float | None:
        """A token's dollar price from Aave's oracle (eight decimals), when Aave lists it."""
        try:
            result = await self._call(
                ctx, self._chain["aave_oracle"], "0xb3596f07" + token[2:].rjust(64, "0")
            )
        except ValueError:
            return None
        price = word(result, 0) / 1e8
        return price or None

    async def _token(self, ctx: Context, token: str, known: dict[str, Any]) -> tuple[str, int]:
        """A token's symbol and decimals, remembered."""
        if token in known:
            return tuple(known[token])  # type: ignore[return-value]
        for symbol, (address, decimals) in self._chain["tokens"].items():
            if address == token:
                known[token] = [symbol, decimals]
                return symbol, decimals
        try:
            symbol = text_of(await self._call(ctx, token, "0x95d89b41")) or short_address(token)
            decimals = word(await self._call(ctx, token, "0x313ce567"), 0) or 18
        except ValueError:
            symbol, decimals = short_address(token), 18
        known[token] = [symbol[:20], decimals]
        return symbol[:20], decimals

    async def _logs(
        self, ctx: Context, state: dict[str, Any], key: str, address: str | list[str], topics: list
    ) -> list[dict[str, Any]]:
        """Logs since the last run (a first run reads about the last hour), in ranges the
        public endpoints accept."""
        latest = int(await self._rpc(ctx, "eth_blockNumber", []), 16) - LAG
        hour = 3600 // self._chain["block_seconds"]
        start = int(state.get(key) or latest - hour) + 1
        start = max(start, latest - MAX_RANGE * KEEP_UP)  # too far behind: skip ahead
        found: list[dict[str, Any]] = []
        while start <= latest:
            end = min(start + MAX_RANGE - 1, latest)
            found += await self._rpc(
                ctx,
                "eth_getLogs",
                [
                    {
                        "address": address,
                        "topics": topics,
                        "fromBlock": hex(start),
                        "toBlock": hex(end),
                    }
                ],
            )
            state[key] = end
            start = end + 1
        return found

    async def _block_time(self, ctx: Context, block: str, times: dict[str, str]) -> str:
        if block not in times:
            header = await self._rpc(ctx, "eth_getBlockByNumber", [block, False])
            when = datetime.fromtimestamp(int(header["timestamp"], 16), UTC)
            times[block] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        return times[block]

    def _event(self, kind: str, key: str, item: dict[str, Any]) -> Event:
        return Event(
            source=self.name,
            type=kind,
            source_url=item["link"],
            key=key,
            timestamp=item["published_at"],
            data=item,
            metadata={"method": f"evm-{self.resource}", "chain": self.chain},
        )

    async def collect(self, ctx: Context):
        path = state_path(ctx, "evm", self.namespace or f"{self.resource}-{self.chain}")
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        state.setdefault("tokens", {})
        try:
            if self.resource == "aave":
                events = await self._aave(ctx)
            elif self.resource == "liquidations":
                events = await self._liquidations(ctx, state)
            elif self.resource == "transfers":
                events = await self._transfers(ctx, state)
            else:
                events = await self._new_pools(ctx, state)
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=self._chain["rpc"])) is not None:
                yield error
            return
        except (ValueError, KeyError, TypeError) as exc:
            ctx.warn(f"evm: {self._chain['name']} answered something unreadable ({exc})")
            return
        finally:
            if self.resource != "aave":
                write_json_atomic(path, state)
        for event in events:
            yield event

    async def _aave(self, ctx: Context) -> list[Event]:
        now = datetime.now(UTC)
        found = []
        for symbol, (token, _) in self._chain["tokens"].items():
            try:
                result = await self._call(
                    ctx, self._chain["aave_data"], "0x35ea6a75" + token[2:].rjust(64, "0")
                )
            except ValueError:
                continue  # not an Aave market on this chain
            market = utilization(result)
            if not market["supplied"] or market["utilization"] < self.min_utilization:
                continue
            chain = self._chain["name"]
            share = market["utilization"] * 100
            item = {
                "title": f"Aave {chain} {symbol} {share:.1f}% used: borrowing costs "
                f"{market['borrow_rate'] * 100:.2f}% a year, lenders earn "
                f"{market['supply_rate'] * 100:.2f}%",
                "summary": f"On Aave V3 ({chain}), {share:.1f}% of the {symbol} supplied is "
                "borrowed; near 100% lenders cannot withdraw until borrowers repay, and the "
                "borrowing rate jumps. Read from Aave's contracts. Data, not investment advice.",
                "link": f"https://app.aave.com/reserve-overview/?underlyingAsset={token}"
                f"&marketName=proto_{'mainnet' if self.chain == 'ethereum' else 'base'}_v3",
                "published_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "symbol": symbol,
                "utilization": round(market["utilization"], 4),
                "borrow_rate": round(market["borrow_rate"], 6),
                "supply_rate": round(market["supply_rate"], 6),
            }
            found.append(self._event("aave-market", f"{self.chain}:{symbol}:{now:%Y-%m-%d}", item))
        return found

    async def _liquidations(self, ctx: Context, state: dict[str, Any]) -> list[Event]:
        from unlimitedpipe.expr import short_number

        logs = await self._logs(ctx, state, "last_block", self._chain["aave_pool"], [LIQUIDATION])
        times: dict[str, str] = {}
        found = []
        for log in logs:
            collateral, debt = address_of(log["topics"][1]), address_of(log["topics"][2])
            user = address_of(log["topics"][3])
            debt_symbol, debt_decimals = await self._token(ctx, debt, state["tokens"])
            collateral_symbol, _ = await self._token(ctx, collateral, state["tokens"])
            price = await self._price(ctx, debt)
            repaid = word(log["data"], 0) / 10**debt_decimals
            value = repaid * price if price else None
            if value is None or value < self._min:
                continue
            when = await self._block_time(ctx, log["blockNumber"], times)
            chain = self._chain["name"]
            link = f"{self._chain['explorer']}/tx/{log['transactionHash']}"
            found.append(
                self._event(
                    "liquidation",
                    f"{log['transactionHash']}:{log['logIndex']}",
                    {
                        "title": f"Aave {chain} liquidation: ${short_number(value)} of "
                        f"{debt_symbol} debt repaid, {collateral_symbol} collateral seized",
                        "summary": f"A borrower ({short_address(user)}) on Aave V3 ({chain}) was "
                        f"liquidated: {repaid:,.2f} {debt_symbol} (${short_number(value)}) of debt "
                        f"repaid by a liquidator, who took {collateral_symbol} collateral. "
                        "Data, not investment advice.",
                        "link": link,
                        "published_at": when,
                        "value": value,
                    },
                )
            )
        return found

    async def _transfers(self, ctx: Context, state: dict[str, Any]) -> list[Event]:
        from unlimitedpipe.expr import short_number

        tokens = {self._chain["tokens"][s][0]: s for s in self._chain["stablecoins"]}
        logs = await self._logs(ctx, state, "last_block", list(tokens), [TRANSFER])
        # a flash loan sends money out and back in one transaction: no flow
        legs = {
            (log["transactionHash"], log["address"].lower(), log["data"], *log["topics"][1:3])
            for log in logs
            if len(log["topics"]) >= 3
        }
        times: dict[str, str] = {}
        found = []
        for log in logs:
            if (
                len(log["topics"]) >= 3
                and (
                    log["transactionHash"],
                    log["address"].lower(),
                    log["data"],
                    log["topics"][2],
                    log["topics"][1],
                )
                in legs
            ):
                continue
            symbol = tokens.get(log["address"].lower())
            if symbol is None or len(log["topics"]) < 3:
                continue
            decimals = self._chain["tokens"][symbol][1]
            amount = word(log["data"], 0) / 10**decimals
            if amount < self._min:
                continue
            sender, receiver = address_of(log["topics"][1]), address_of(log["topics"][2])
            chain = self._chain["name"]
            if sender == ZERO:
                what = f"${short_number(amount)} {symbol} minted on {chain}"
            elif receiver == ZERO:
                what = f"${short_number(amount)} {symbol} burned on {chain}"
            else:
                what = (
                    f"${short_number(amount)} {symbol} moved on {chain}: "
                    f"{short_address(sender)} to {short_address(receiver)}"
                )
            when = await self._block_time(ctx, log["blockNumber"], times)
            found.append(
                self._event(
                    "transfer",
                    f"{log['transactionHash']}:{log['logIndex']}",
                    {
                        "title": what,
                        "summary": f"{what} (from {sender} to {receiver}), in block "
                        f"{int(log['blockNumber'], 16)}. Data, not investment advice.",
                        "link": f"{self._chain['explorer']}/tx/{log['transactionHash']}",
                        "published_at": when,
                        "value": amount,
                    },
                )
            )
        return found

    async def _new_pools(self, ctx: Context, state: dict[str, Any]) -> list[Event]:
        from unlimitedpipe.expr import short_number

        quotes = {self._chain["tokens"][s][0]: s for s in ("WETH", "USDC", "USDT")}
        pending: dict[str, dict[str, Any]] = state.setdefault("pending", {})
        for version, factory, topic in (
            ("V3", self._chain["uniswap_v3"], POOL_CREATED),
            ("V2", self._chain["uniswap_v2"], PAIR_CREATED),
        ):
            for log in await self._logs(ctx, state, f"last_block_{version}", factory, [topic]):
                token0, token1 = address_of(log["topics"][1]), address_of(log["topics"][2])
                quote = token1 if token1 in quotes else token0 if token0 in quotes else None
                if quote is None:
                    continue
                other = token0 if quote == token1 else token1
                # V3: (tickSpacing, pool); V2: (pair, count)
                pool = address_of(word_hex(log["data"], 1 if version == "V3" else 0))
                pending[pool] = {
                    "version": version,
                    "token": other,
                    "quote": quote,
                    "since": datetime.now(UTC).timestamp(),
                    "tx": log["transactionHash"],
                }
        prices = {q: await self._price(ctx, q) for q in quotes}
        now = datetime.now(UTC)
        found = []
        for pool, entry in list(pending.items()):
            if now.timestamp() - entry["since"] > PENDING_HOURS * 3600:
                del pending[pool]
                continue
            quote = entry["quote"]
            decimals = self._chain["tokens"][quotes[quote]][1]
            balance = word(await self._call(ctx, quote, "0x70a08231" + pool[2:].rjust(64, "0")), 0)
            value = balance / 10**decimals * (prices.get(quote) or 0)
            if value < self._min:
                continue
            del pending[pool]
            token_symbol, _ = await self._token(ctx, entry["token"], state["tokens"])
            pair = f"{token_symbol}/{quotes[quote]}"
            found.append(
                self._event(
                    "new-pool",
                    pool,
                    {
                        "title": f"New Uniswap {entry['version']} pool {pair} with "
                        f"${short_number(value)} of {quotes[quote]} in it",
                        "summary": f"A new Uniswap {entry['version']} pool on Ethereum trades "
                        f"{token_symbol} ({entry['token']}) against {quotes[quote]}, and holds "
                        f"${short_number(value)} of {quotes[quote]}. New tokens are often scams; "
                        "check the contract. Data, not investment advice.",
                        "link": f"{self._chain['explorer']}/address/{pool}",
                        "published_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "value": value,
                    },
                )
            )
        if len(pending) > 500:  # keep the newest
            for pool in sorted(pending, key=lambda p: pending[p]["since"])[: len(pending) - 500]:
                del pending[pool]
        return found

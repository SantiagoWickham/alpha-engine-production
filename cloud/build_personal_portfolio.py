import csv
import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

LEDGER_PATH = (
    ROOT
    / "PRODUCT"
    / "personal_portfolio_ledger.json"
)

SUMMARY_PATH = (
    ROOT
    / "PRODUCT"
    / "personal_portfolio.json"
)

POSITIONS_JSON_PATH = (
    ROOT
    / "PRODUCT"
    / "personal_portfolio_positions.json"
)

POSITIONS_CSV_PATH = (
    ROOT
    / "PRODUCT"
    / "personal_portfolio_positions.csv"
)

CASH_JSON_PATH = (
    ROOT
    / "PRODUCT"
    / "personal_portfolio_cash.json"
)

SNAPSHOT_PATH = (
    ROOT
    / "PRODUCT"
    / "personal_portfolio_snapshot.json"
)


ALLOWED_OPERATIONS = {
    "BUY",
    "SELL",
    "DIVIDEND",
    "DEPOSIT",
    "WITHDRAWAL",
    "FEE",
    "INTEREST",
    "TAX",
}


EPS = 1e-10


# ============================================================
# HELPERS
# ============================================================

def clean_text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def upper_text(value: Any) -> str:
    return clean_text(value).upper()


def to_float(
    value: Any,
    *,
    default: float | None = None,
    field: str = "",
) -> float | None:

    if value is None:
        return default

    if isinstance(value, str):
        value = value.strip()

        if value == "":
            return default

        value = value.replace(",", ".")

    try:
        result = float(value)

    except (TypeError, ValueError):
        raise ValueError(
            f"INVALID_NUMERIC_VALUE | "
            f"field={field} | "
            f"value={value!r}"
        )

    if not math.isfinite(result):
        raise ValueError(
            f"NON_FINITE_NUMERIC_VALUE | "
            f"field={field} | "
            f"value={value!r}"
        )

    return result


def require_non_negative(
    value: float,
    field: str,
) -> float:

    if value < -EPS:
        raise ValueError(
            f"NEGATIVE_VALUE_NOT_ALLOWED | "
            f"field={field} | "
            f"value={value}"
        )

    return max(value, 0.0)


def parse_date(value: Any) -> str:
    text = clean_text(value)

    if not text:
        return ""

    return text


def get_field(
    row: dict[str, Any],
    *names: str,
    default: Any = None,
) -> Any:

    for name in names:
        if name in row:
            return row[name]

    return default


# ============================================================
# POSITION MODEL
# ============================================================

@dataclass
class PositionState:
    ticker: str

    quantity: float = 0.0

    cost_basis_usd: float = 0.0

    realized_pnl_usd: float = 0.0

    buy_gross_usd: float = 0.0

    sell_gross_usd: float = 0.0

    fees_usd: float = 0.0

    buy_count: int = 0

    sell_count: int = 0


    @property
    def average_cost_usd(self) -> float | None:

        if self.quantity <= EPS:
            return None

        return (
            self.cost_basis_usd
            / self.quantity
        )


# ============================================================
# LEDGER LOAD
# ============================================================

def load_ledger() -> dict[str, Any]:

    if not LEDGER_PATH.exists():
        raise FileNotFoundError(
            f"MISSING_LEDGER: {LEDGER_PATH}"
        )

    ledger = json.loads(
        LEDGER_PATH.read_text(
            encoding="utf-8"
        )
    )

    operations = ledger.get(
        "operations",
        []
    )

    cash = ledger.get(
        "cash",
        []
    )

    if not isinstance(
        operations,
        list,
    ):
        raise ValueError(
            "LEDGER_OPERATIONS_NOT_LIST"
        )

    if not isinstance(
        cash,
        list,
    ):
        raise ValueError(
            "LEDGER_CASH_NOT_LIST"
        )

    return ledger


# ============================================================
# INITIAL CASH
# ============================================================

def build_initial_cash(
    cash_rows: list[dict[str, Any]],
) -> tuple[float, list[dict[str, Any]]]:

    total_usd = 0.0

    normalized = []


    for index, row in enumerate(
        cash_rows,
        start=1,
    ):

        currency = upper_text(
            get_field(
                row,
                "Moneda",
                "currency",
            )
        )

        balance = to_float(
            get_field(
                row,
                "Saldo Inicial",
                "Saldo",
                "balance",
            ),
            default=0.0,
            field=f"cash[{index}].balance",
        )

        fx = to_float(
            get_field(
                row,
                "FX a USD",
                "fx_to_usd",
            ),
            default=(
                1.0
                if currency == "USD"
                else None
            ),
            field=f"cash[{index}].fx_to_usd",
        )

        value_usd = to_float(
            get_field(
                row,
                "Valor Inicial USD",
                "value_usd",
            ),
            default=None,
            field=f"cash[{index}].value_usd",
        )


        if value_usd is None:

            if balance is None:
                balance = 0.0

            if abs(balance) <= EPS:
                value_usd = 0.0

            elif fx is None:
                raise ValueError(
                    "CASH_FX_REQUIRED | "
                    f"row={index} | "
                    f"currency={currency}"
                )

            else:
                value_usd = (
                    balance
                    * fx
                )


        total_usd += value_usd


        normalized.append({

            "currency":
                currency,

            "initial_balance":
                balance,

            "initial_date":
                parse_date(
                    get_field(
                        row,
                        "Fecha Inicial",
                        "date",
                    )
                ),

            "fx_to_usd":
                fx,

            "initial_value_usd":
                value_usd,

            "notes":
                clean_text(
                    get_field(
                        row,
                        "Notas",
                        "notes",
                    )
                ),

        })


    return (
        total_usd,
        normalized,
    )


# ============================================================
# OPERATIONS NORMALIZATION
# ============================================================

def normalize_operations(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:

    normalized = []

    seen_ids = set()


    for index, row in enumerate(
        rows,
        start=1,
    ):

        op_type = upper_text(
            get_field(
                row,
                "Operación",
                "operation",
            )
        )

        if not op_type:
            continue


        if op_type not in ALLOWED_OPERATIONS:
            raise ValueError(
                "INVALID_OPERATION_TYPE | "
                f"row={index} | "
                f"type={op_type}"
            )


        operation_id = clean_text(
            get_field(
                row,
                "ID Operación",
                "operation_id",
            )
        )


        if operation_id:

            if operation_id in seen_ids:
                raise ValueError(
                    "DUPLICATE_OPERATION_ID | "
                    f"id={operation_id}"
                )

            seen_ids.add(
                operation_id
            )


        currency = upper_text(
            get_field(
                row,
                "Moneda",
                "currency",
                default="USD",
            )
        ) or "USD"


        fx = to_float(
            get_field(
                row,
                "FX a USD",
                "fx_to_usd",
            ),
            default=(
                1.0
                if currency == "USD"
                else None
            ),
            field=f"operation[{index}].fx",
        )


        quantity = to_float(
            get_field(
                row,
                "Cantidad",
                "quantity",
            ),
            default=0.0,
            field=f"operation[{index}].quantity",
        )

        price = to_float(
            get_field(
                row,
                "Precio",
                "price",
            ),
            default=0.0,
            field=f"operation[{index}].price",
        )

        costs = to_float(
            get_field(
                row,
                "Costos",
                "costs",
            ),
            default=0.0,
            field=f"operation[{index}].costs",
        )

        amount_usd = to_float(
            get_field(
                row,
                "Importe USD",
                "amount_usd",
            ),
            default=None,
            field=f"operation[{index}].amount_usd",
        )


        quantity = require_non_negative(
            quantity,
            f"operation[{index}].quantity",
        )

        price = require_non_negative(
            price,
            f"operation[{index}].price",
        )

        costs = require_non_negative(
            costs,
            f"operation[{index}].costs",
        )


        if fx is not None:
            fx = require_non_negative(
                fx,
                f"operation[{index}].fx",
            )


        # Costs are assumed to be denominated
        # in the operation currency.
        #
        # USD operation -> costs USD.
        # ARS operation -> costs ARS, converted via FX.

        if costs > EPS:

            if fx is None:
                raise ValueError(
                    "FX_REQUIRED_FOR_COSTS | "
                    f"row={index}"
                )

            costs_usd = (
                costs
                * fx
            )

        else:
            costs_usd = 0.0


        gross_usd = None


        if (
            quantity > EPS
            and price > EPS
        ):

            if fx is None:
                raise ValueError(
                    "FX_REQUIRED_FOR_TRADE | "
                    f"row={index}"
                )

            gross_usd = (
                quantity
                * price
                * fx
            )


        if amount_usd is None:
            amount_usd = gross_usd


        normalized.append({

            "_sequence":
                index,

            "date":
                parse_date(
                    get_field(
                        row,
                        "Fecha",
                        "date",
                    )
                ),

            "account":
                clean_text(
                    get_field(
                        row,
                        "Cuenta",
                        "account",
                        default="Principal",
                    )
                ) or "Principal",

            "ticker":
                upper_text(
                    get_field(
                        row,
                        "Ticker",
                        "ticker",
                    )
                ),

            "operation":
                op_type,

            "quantity":
                quantity,

            "price":
                price,

            "currency":
                currency,

            "fx_to_usd":
                fx,

            "costs":
                costs,

            "costs_usd":
                costs_usd,

            "gross_usd":
                gross_usd,

            "amount_usd":
                amount_usd,

            "operation_id":
                operation_id,

            "source":
                clean_text(
                    get_field(
                        row,
                        "Fuente",
                        "source",
                    )
                ),

            "notes":
                clean_text(
                    get_field(
                        row,
                        "Notas",
                        "notes",
                    )
                ),

        })


    normalized.sort(
        key=lambda x: (
            x["date"],
            x["_sequence"],
        )
    )


    return normalized


# ============================================================
# ENGINE
# ============================================================

def run_engine(
    initial_cash_usd: float,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:

    positions: dict[
        str,
        PositionState
    ] = {}


    cash_usd = initial_cash_usd

    realized_pnl_total_usd = 0.0

    portfolio_fees_usd = 0.0

    dividends_usd = 0.0

    interest_usd = 0.0

    taxes_usd = 0.0

    deposits_usd = 0.0

    withdrawals_usd = 0.0


    for op in operations:

        op_type = op["operation"]

        ticker = op["ticker"]

        quantity = op["quantity"]

        gross_usd = op["gross_usd"]

        amount_usd = op["amount_usd"]

        costs_usd = op["costs_usd"]


        # ----------------------------------------------------
        # BUY
        # ----------------------------------------------------

        if op_type == "BUY":

            if not ticker:
                raise ValueError(
                    "BUY_REQUIRES_TICKER"
                )

            if quantity <= EPS:
                raise ValueError(
                    "BUY_REQUIRES_POSITIVE_QUANTITY | "
                    f"ticker={ticker}"
                )

            if (
                gross_usd is None
                or gross_usd <= EPS
            ):
                raise ValueError(
                    "BUY_REQUIRES_PRICE_AND_FX | "
                    f"ticker={ticker}"
                )


            position = positions.setdefault(
                ticker,
                PositionState(
                    ticker=ticker
                ),
            )


            total_cost_usd = (
                gross_usd
                + costs_usd
            )


            position.quantity += (
                quantity
            )

            position.cost_basis_usd += (
                total_cost_usd
            )

            position.buy_gross_usd += (
                gross_usd
            )

            position.fees_usd += (
                costs_usd
            )

            position.buy_count += 1


            cash_usd -= (
                total_cost_usd
            )

            portfolio_fees_usd += (
                costs_usd
            )


        # ----------------------------------------------------
        # SELL
        # ----------------------------------------------------

        elif op_type == "SELL":

            if not ticker:
                raise ValueError(
                    "SELL_REQUIRES_TICKER"
                )

            if quantity <= EPS:
                raise ValueError(
                    "SELL_REQUIRES_POSITIVE_QUANTITY | "
                    f"ticker={ticker}"
                )

            if (
                gross_usd is None
                or gross_usd <= EPS
            ):
                raise ValueError(
                    "SELL_REQUIRES_PRICE_AND_FX | "
                    f"ticker={ticker}"
                )


            if ticker not in positions:
                raise ValueError(
                    "SELL_WITHOUT_POSITION | "
                    f"ticker={ticker}"
                )


            position = positions[
                ticker
            ]


            if (
                quantity
                >
                position.quantity
                + EPS
            ):
                raise ValueError(
                    "SELL_EXCEEDS_POSITION | "
                    f"ticker={ticker} | "
                    f"sell={quantity} | "
                    f"held={position.quantity}"
                )


            avg_cost = (
                position.average_cost_usd
                or 0.0
            )


            removed_basis = (
                avg_cost
                * quantity
            )


            net_proceeds = (
                gross_usd
                - costs_usd
            )


            realized_pnl = (
                net_proceeds
                - removed_basis
            )


            position.quantity -= (
                quantity
            )

            position.cost_basis_usd -= (
                removed_basis
            )

            position.sell_gross_usd += (
                gross_usd
            )

            position.fees_usd += (
                costs_usd
            )

            position.sell_count += 1

            position.realized_pnl_usd += (
                realized_pnl
            )


            if (
                abs(
                    position.quantity
                )
                <= EPS
            ):

                position.quantity = 0.0

                position.cost_basis_usd = 0.0


            cash_usd += (
                net_proceeds
            )

            realized_pnl_total_usd += (
                realized_pnl
            )

            portfolio_fees_usd += (
                costs_usd
            )


        # ----------------------------------------------------
        # DEPOSIT
        # ----------------------------------------------------

        elif op_type == "DEPOSIT":

            if amount_usd is None:
                raise ValueError(
                    "DEPOSIT_REQUIRES_AMOUNT_USD"
                )

            cash_usd += (
                amount_usd
            )

            deposits_usd += (
                amount_usd
            )


        # ----------------------------------------------------
        # WITHDRAWAL
        # ----------------------------------------------------

        elif op_type == "WITHDRAWAL":

            if amount_usd is None:
                raise ValueError(
                    "WITHDRAWAL_REQUIRES_AMOUNT_USD"
                )

            cash_usd -= (
                amount_usd
            )

            withdrawals_usd += (
                amount_usd
            )


        # ----------------------------------------------------
        # DIVIDEND
        # ----------------------------------------------------

        elif op_type == "DIVIDEND":

            if amount_usd is None:
                raise ValueError(
                    "DIVIDEND_REQUIRES_AMOUNT_USD"
                )

            net_amount = (
                amount_usd
                - costs_usd
            )

            cash_usd += (
                net_amount
            )

            dividends_usd += (
                net_amount
            )

            portfolio_fees_usd += (
                costs_usd
            )


        # ----------------------------------------------------
        # INTEREST
        # ----------------------------------------------------

        elif op_type == "INTEREST":

            if amount_usd is None:
                raise ValueError(
                    "INTEREST_REQUIRES_AMOUNT_USD"
                )

            net_amount = (
                amount_usd
                - costs_usd
            )

            cash_usd += (
                net_amount
            )

            interest_usd += (
                net_amount
            )

            portfolio_fees_usd += (
                costs_usd
            )


        # ----------------------------------------------------
        # FEE
        # ----------------------------------------------------

        elif op_type == "FEE":

            fee_amount = (
                amount_usd
                if amount_usd is not None
                else costs_usd
            )


            if fee_amount is None:
                raise ValueError(
                    "FEE_REQUIRES_AMOUNT"
                )


            cash_usd -= (
                fee_amount
            )

            portfolio_fees_usd += (
                fee_amount
            )


        # ----------------------------------------------------
        # TAX
        # ----------------------------------------------------

        elif op_type == "TAX":

            tax_amount = (
                amount_usd
                if amount_usd is not None
                else costs_usd
            )


            if tax_amount is None:
                raise ValueError(
                    "TAX_REQUIRES_AMOUNT"
                )


            cash_usd -= (
                tax_amount
            )

            taxes_usd += (
                tax_amount
            )


    active_positions = []


    for ticker in sorted(
        positions.keys()
    ):

        position = positions[
            ticker
        ]


        if (
            position.quantity
            <= EPS
        ):
            continue


        active_positions.append({

            "ticker":
                ticker,

            "quantity":
                position.quantity,

            "average_cost_usd":
                position.average_cost_usd,

            "cost_basis_usd":
                position.cost_basis_usd,

            "realized_pnl_usd":
                position.realized_pnl_usd,

            "buy_gross_usd":
                position.buy_gross_usd,

            "sell_gross_usd":
                position.sell_gross_usd,

            "fees_usd":
                position.fees_usd,

            "buy_count":
                position.buy_count,

            "sell_count":
                position.sell_count,

            # Filled by market valuation layer later.
            "current_price_usd":
                None,

            "market_value_usd":
                None,

            "unrealized_pnl_usd":
                None,

            "unrealized_pnl_pct":
                None,

            "portfolio_weight":
                None,

            "price_source":
                None,

        })


    total_cost_basis_usd = sum(
        row["cost_basis_usd"]
        for row in active_positions
    )


    book_value_usd = (
        cash_usd
        + total_cost_basis_usd
    )


    if (
        not operations
        and abs(initial_cash_usd) <= EPS
    ):

        status = (
            "EMPTY_PORTFOLIO"
        )

    elif active_positions:

        status = (
            "READY_AWAITING_MARKET_VALUATION"
        )

    else:

        status = (
            "CASH_ONLY"
        )


    return {

        "status":
            status,

        "cash_usd":
            cash_usd,

        "initial_cash_usd":
            initial_cash_usd,

        "book_value_usd":
            book_value_usd,

        "market_nav_usd":
            None,

        "total_cost_basis_usd":
            total_cost_basis_usd,

        "realized_pnl_usd":
            realized_pnl_total_usd,

        "dividends_usd":
            dividends_usd,

        "interest_usd":
            interest_usd,

        "fees_usd":
            portfolio_fees_usd,

        "taxes_usd":
            taxes_usd,

        "deposits_usd":
            deposits_usd,

        "withdrawals_usd":
            withdrawals_usd,

        "positions":
            active_positions,

    }


# ============================================================
# OUTPUT
# ============================================================

def write_positions_csv(
    positions: list[dict[str, Any]],
) -> None:

    headers = [

        "ticker",

        "quantity",

        "average_cost_usd",

        "cost_basis_usd",

        "current_price_usd",

        "market_value_usd",

        "realized_pnl_usd",

        "unrealized_pnl_usd",

        "unrealized_pnl_pct",

        "portfolio_weight",

        "price_source",

        "buy_count",

        "sell_count",

        "fees_usd",

    ]


    with POSITIONS_CSV_PATH.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=headers,
        )

        writer.writeheader()


        for row in positions:

            writer.writerow({

                key:
                    row.get(key)

                for key in headers

            })


def main() -> None:

    ledger = load_ledger()


    operations_raw = ledger.get(
        "operations",
        []
    )

    cash_raw = ledger.get(
        "cash",
        []
    )


    (
        initial_cash_usd,
        normalized_cash,
    ) = build_initial_cash(
        cash_raw
    )


    operations = normalize_operations(
        operations_raw
    )


    result = run_engine(
        initial_cash_usd,
        operations,
    )


    generated_at = datetime.now(
        timezone.utc
    ).isoformat()


    positions = result[
        "positions"
    ]


    summary = {

        "schema":
            "ALPHA_ENGINE_PERSONAL_PORTFOLIO_V1",

        "generated_at_utc":
            generated_at,

        "source":
            "GOOGLE_SHEETS_LEDGER",

        "status":
            result["status"],

        "operations_count":
            len(operations),

        "positions_count":
            len(positions),

        "initial_cash_usd":
            result["initial_cash_usd"],

        "cash_usd":
            result["cash_usd"],

        "total_cost_basis_usd":
            result["total_cost_basis_usd"],

        "book_value_usd":
            result["book_value_usd"],

        "nav":
            None,

        "market_nav_usd":
            None,

        "cagr":
            None,

        "max_drawdown":
            None,

        "realized_pnl_usd":
            result["realized_pnl_usd"],

        "dividends_usd":
            result["dividends_usd"],

        "interest_usd":
            result["interest_usd"],

        "fees_usd":
            result["fees_usd"],

        "taxes_usd":
            result["taxes_usd"],

        "deposits_usd":
            result["deposits_usd"],

        "withdrawals_usd":
            result["withdrawals_usd"],

        "market_prices_connected":
            False,

        "note":
            (
                "Portfolio ledger reconstructed. "
                "Market NAV, unrealized P&L, weights, "
                "CAGR and drawdown require market-price layer."
            ),

    }


    cash_output = {

        "schema":
            "ALPHA_ENGINE_PERSONAL_CASH_V1",

        "generated_at_utc":
            generated_at,

        "initial_cash_rows":
            normalized_cash,

        "initial_cash_usd":
            result["initial_cash_usd"],

        "current_cash_usd":
            result["cash_usd"],

        "deposits_usd":
            result["deposits_usd"],

        "withdrawals_usd":
            result["withdrawals_usd"],

        "dividends_usd":
            result["dividends_usd"],

        "interest_usd":
            result["interest_usd"],

        "fees_usd":
            result["fees_usd"],

        "taxes_usd":
            result["taxes_usd"],

    }


    positions_output = {

        "schema":
            "ALPHA_ENGINE_PERSONAL_POSITIONS_V1",

        "generated_at_utc":
            generated_at,

        "positions_count":
            len(positions),

        "positions":
            positions,

    }


    snapshot = {

        "schema":
            "ALPHA_ENGINE_PERSONAL_SNAPSHOT_V1",

        "generated_at_utc":
            generated_at,

        "summary":
            summary,

        "cash":
            cash_output,

        "positions":
            positions,

    }


    SUMMARY_PATH.write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    CASH_JSON_PATH.write_text(
        json.dumps(
            cash_output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    POSITIONS_JSON_PATH.write_text(
        json.dumps(
            positions_output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    SNAPSHOT_PATH.write_text(
        json.dumps(
            snapshot,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    write_positions_csv(
        positions
    )


    print()
    print(
        "============================================================"
    )
    print(
        "ALPHA ENGINE - PERSONAL PORTFOLIO ENGINE"
    )
    print(
        "============================================================"
    )
    print()

    print(
        f"OPERATIONS:           {len(operations)}"
    )

    print(
        f"POSITIONS:            {len(positions)}"
    )

    print(
        f"INITIAL CASH USD:     "
        f"{result['initial_cash_usd']:.2f}"
    )

    print(
        f"CURRENT CASH USD:     "
        f"{result['cash_usd']:.2f}"
    )

    print(
        f"COST BASIS USD:       "
        f"{result['total_cost_basis_usd']:.2f}"
    )

    print(
        f"BOOK VALUE USD:       "
        f"{result['book_value_usd']:.2f}"
    )

    print(
        f"REALIZED P&L USD:     "
        f"{result['realized_pnl_usd']:.2f}"
    )

    print(
        f"STATUS:               "
        f"{result['status']}"
    )

    print()

    print(
        f"SUMMARY:              "
        f"{SUMMARY_PATH}"
    )

    print(
        f"POSITIONS:            "
        f"{POSITIONS_JSON_PATH}"
    )

    print(
        f"CASH:                 "
        f"{CASH_JSON_PATH}"
    )

    print()

    print(
        "PERSONAL PORTFOLIO ENGINE: PASS"
    )

    print(
        "============================================================"
    )


if __name__ == "__main__":
    main()

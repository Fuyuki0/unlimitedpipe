from unlimitedpipe.sources.fec import cycle_of, outside_spending

HEADER = (
    "cand_id,cand_name,spe_id,spe_nam,ele_type,can_office_state,can_office_dis,can_office,"
    "cand_pty_aff,exp_amo,exp_date,agg_amo,sup_opp,pur,pay,file_num,amndt_ind,tran_id,"
    "image_num,receipt_dat,fec_election_yr,prev_file_num,dissem_dt\n"
)


def row(spender, name, amount, side, office, state, district, amend, tran, filed, shown):
    return (
        f'"S6TX00000","{name}","{spender}","X","G","{state}","{district}","{office}","DEM",'
        f'"{amount}","","{amount}","{side}","MEDIA","ADS LLC","1","{amend}","{tran}","999",'
        f'"{filed}","2026","","{shown}"\n'
    )


def test_outside_spending_keeps_listed_committees_and_the_latest_amendment():
    table = HEADER + "".join(
        [
            row(
                "C1",
                "TALARICO, JAMES",
                "1000000",
                "O",
                "S",
                "TX",
                "00",
                "N",
                "T1",
                "01-OCT-26",
                "13-OCT-26",
            ),
            row(
                "C1",
                "TALARICO, JAMES",
                "1200000",
                "O",
                "S",
                "TX",
                "00",
                "A1",
                "T1",
                "02-OCT-26",
                "13-OCT-26",
            ),
            row(
                "C9",
                "BETTIS, SHAWN",
                "9000000000",
                "O",
                "P",
                "FL",
                "00",
                "N",
                "T2",
                "03-APR-26",
                "",
            ),  # a made-up form: not a listed committee
            row("C1", "DOE, JANE", "50000", "S", "H", "OH", "09", "N", "T3", "01-SEP-26", ""),
        ]
    )
    found = outside_spending(table, {"C1": "TEXAS PAC"}, min_value=250000)
    assert [f["title"] for f in found] == [
        "Texas PAC spent $1.2M opposing James Talarico for the Senate (TX)"
    ]
    assert found[0]["published_at"] == "2026-10-02T00:00:00Z"  # filed, not when ads run
    assert "To be seen from 2026-10-13" in found[0]["summary"]
    assert cycle_of(__import__("datetime").datetime(2025, 3, 1)) == 2026

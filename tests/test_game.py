import pytest

from fieldhand import config, game


def total_money(village):
    with village.world.tx() as db:
        return db.execute("SELECT SUM(coins) FROM players").fetchone()[0]


def state(village, pid):
    return village.do(game.player_state, pid)


def new_player(village, name, land=True):
    pid = village.do(game.register, name)["player_id"]
    if land:
        village.do(game.claim, pid)
    return pid


def test_register_gives_coins_and_a_free_plot(village):
    pid = village.do(game.register, "ana")["player_id"]
    me = state(village, pid)
    assert me["coins"] == config.START_COINS
    assert me["plots"] == []
    assert village.do(game.claim, pid)["plot_id"] == 1


def test_only_landless_players_can_claim(village):
    pid = new_player(village, "ana")
    village.do(game.register, "bob")
    with pytest.raises(game.GameError, match="without land"):
        village.do(game.claim, pid)


def test_one_workday_per_day(village):
    pid = new_player(village, "ana")
    village.do(game.harvest, pid, 1)
    assert state(village, pid)["rations"] == config.RATIONS_PER_HARVEST
    with pytest.raises(game.GameError, match="workday"):
        village.do(game.harvest, pid, 1)


def test_job_pays_wage_and_owner_gets_the_rations(village):
    owner = new_player(village, "ana")
    worker = new_player(village, "bob", land=False)
    # Ana gets a second plot by buying it from Cris.
    seller = village.do(game.register, "cris")["player_id"]
    plot = village.do(game.claim, seller)["plot_id"]
    oid = village.do(game.post_offer, seller, "sell_land", 10_000, 1, plot)["offer_id"]
    village.do(game.accept_offer, owner, oid)
    money = total_money(village)

    job = village.do(game.post_offer, owner, "job", 1_500, 1, plot)["offer_id"]
    village.do(game.accept_offer, worker, job)

    assert state(village, owner)["rations"] == config.RATIONS_PER_HARVEST
    assert state(village, owner)["coins"] == 50 - 10 - 1.5
    assert state(village, worker)["coins"] == 50 + 1.5
    assert state(village, worker)["worked_today"]
    assert total_money(village) == money


def test_ration_trade_conserves_money_and_keeps_expiry(village):
    seller = new_player(village, "ana")
    buyer = new_player(village, "bob", land=False)
    village.do(game.harvest, seller, 1)
    money = total_money(village)

    oid = village.do(game.post_offer, seller, "sell_rations", 400, 2)["offer_id"]
    village.do(game.accept_offer, buyer, oid, 1)

    assert state(village, buyer)["rations"] == 1
    assert state(village, buyer)["ration_lots"] == state(village, seller)["ration_lots"]
    assert total_money(village) == money
    assert village.do(game.list_offers)[0]["qty"] == 1


def test_offer_withdrawn_if_author_cannot_honour_it(village):
    seller = new_player(village, "ana")
    buyer = new_player(village, "bob", land=False)
    village.do(game.harvest, seller, 1)
    oid = village.do(game.post_offer, seller, "sell_rations", 400, 2)["offer_id"]
    village.do(game.eat, seller, 2)
    with pytest.raises(game.GameError, match="withdrawn"):
        village.do(game.accept_offer, buyer, oid, 1)
    assert village.do(game.list_offers) == []


def test_newcomer_has_two_days_to_eat(village):
    pid = new_player(village, "ana")
    assert state(village, pid)["must_eat_by_day"] == 2
    village.next_day()
    assert state(village, pid)["deaths"] == 0
    village.next_day()
    assert state(village, pid)["deaths"] == 1


def test_one_day_without_eating_does_not_kill(village):
    pid = new_player(village, "ana")
    village.do(game.harvest, pid, 1)
    village.do(game.eat, pid, 1)
    village.next_day()
    village.next_day()
    assert state(village, pid)["deaths"] == 0
    assert state(village, pid)["must_eat_by_day"] == 3


def test_two_days_without_eating_kill_and_free_the_land(village):
    pid = new_player(village, "ana")
    village.do(game.harvest, pid, 1)
    village.next_day()
    village.next_day()

    me = state(village, pid)
    assert me["deaths"] == 1
    assert me["coins"] == 0
    assert me["rations"] == 0
    assert me["plots"] == []
    assert me["must_eat_by_day"] == 4
    assert village.do(game.claim, pid)["plot_id"] == 1


def test_eating_keeps_you_alive_and_scores(village):
    pid = new_player(village, "ana")
    village.next_day()
    village.do(game.harvest, pid, 1)
    village.do(game.eat, pid, 2)
    village.next_day()
    me = state(village, pid)
    assert me["deaths"] == 0
    assert me["eaten_total"] == 2
    assert me["days_alive"] == 2


def test_harvest_lasts_seven_days(village):
    pid = new_player(village, "ana")
    village.do(game.harvest, pid, 1)
    assert state(village, pid)["ration_lots"] == [
        {"expires_after_day": config.SPOIL_DAYS, "qty": config.RATIONS_PER_HARVEST}
    ]


def test_rations_spoil_at_the_close_of_their_last_day(village):
    pid = new_player(village, "ana")
    with village.world.tx() as db:
        game._add_rations(db, pid, [(1, 3), (2, 1)])
    village.next_day()
    assert state(village, pid)["ration_lots"] == [{"expires_after_day": 2, "qty": 1}]


def test_day_closes_exactly_on_time(village):
    assert village.world.clock()["day"] == 1
    village.advance(59.5)
    assert village.world.clock()["day"] == 1
    village.advance(0.5)
    assert village.world.clock()["day"] == 2


def test_downtime_pauses_the_world(village):
    pid = new_player(village, "ana")
    village.next_day()
    left = village.world.clock()["seconds_left"]
    # The server is off for an hour: nobody dies and the day resumes where it was.
    village.time.t += 3600
    assert village.world.clock()["day"] == 2
    with village.world.lock:
        village.world._tick(village.time.t)
    assert village.world.clock()["day"] == 2
    assert village.world.clock()["seconds_left"] == pytest.approx(left)
    assert state(village, pid)["deaths"] == 0

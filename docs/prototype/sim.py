"""Simulación de la economía de granjas (reglas acordadas).

Reglas:
1. Al registrarte recibes S monedas y se crea 1 parcela libre.
2. 1 jornada al día = cosechar 1 parcela (propia o ajena por salario).
3. Parcela cosechada = R raciones.
4. Comer mínimo 1 ración/día o mueres. Lo comido = puntuación.
5. Las raciones caducan a los D días.
6. Al morir lo pierdes todo, reapareces sin nada, tu tierra queda libre.
7. Raciones, tierra y trabajo se compran/venden con monedas.

Bots deterministas con distinta preferencia temporal (horizonte H y
propensión a consumir), sin azar.
"""
import statistics as st
from collections import deque

R, D, S = 2, 7, 100.0


class Agent:
    def __init__(self, i, coins):
        self.id = i
        self.coins = coins
        self.food = deque()          # (cantidad, día de caducidad)
        self.parcels = 0
        self.score = 0.0
        self.alive_since = 0
        # Heterogeneidad determinista por id
        self.H = 30 + (i * 37) % 120            # horizonte de 30 a 150 días
        self.beta = 0.02 + ((i * 13) % 10) / 100  # propensión a consumir 2–11 %

    def stock(self):
        return sum(q for q, _ in self.food)

    def take(self, qty):
        got = 0.0
        while qty > 1e-9 and self.food:
            q, e = self.food[0]
            t = min(q, qty)
            got += t
            qty -= t
            if t >= q - 1e-9:
                self.food.popleft()
            else:
                self.food[0] = (q - t, e)
        return got

    def add(self, qty, exp):
        if qty > 1e-9:
            self.food.append((qty, exp))

    def reset(self, day):
        self.coins = 0.0
        self.food.clear()
        self.parcels = 0
        self.alive_since = day


def run(days=180, start=50, reg_every=2, stop_reg_at=None, respawn_coins=0.0, wage_in_food=False):
    agents, free = [], 0
    for i in range(start):
        agents.append(Agent(i, S)); free += 1
    p, w = 1.0, 1.3            # precio ración y salario (monedas)
    log, deaths = [], 0
    for day in range(days):
        # Registros nuevos
        if day > 0 and day % reg_every == 0 and (stop_reg_at is None or day < stop_reg_at):
            agents.append(Agent(len(agents), S)); free += 1
        # Reclamar tierra libre: sin tierra, por orden de id
        for a in sorted(agents, key=lambda a: (a.parcels > 0, a.id)):
            if free == 0:
                break
            if a.parcels == 0:
                a.parcels += 1; free -= 1

        # --- Mercado de tierra (preferencia temporal) ---
        rent = max(R * p - w, 0.0)
        holders = sorted([a for a in agents if a.parcels > 0], key=lambda a: a.H)
        buyers = sorted(agents, key=lambda a: -a.H)
        for s in holders:
            for b in buyers:
                if b is s or s.parcels == 0:
                    continue
                if b.H <= s.H + 20:
                    break
                price = rent * (s.H + b.H) / 2
                if price <= 0 or b.coins < price + 10 * p:
                    continue
                s.parcels -= 1; b.parcels += 1
                b.coins -= price; s.coins += price
                break

        # --- Mercado de trabajo ---
        jobs = sum(max(a.parcels - 1, 0) for a in agents)
        workers = [a for a in agents if a.parcels == 0]
        hired = min(jobs, len(workers))
        if jobs > len(workers):
            w *= 1.03
        elif len(workers) > jobs:
            w *= 0.97
        w = min(max(w, p * 1.0001), R * p)        # entre 1 y R raciones
        # Cosecha
        exp = day + D
        need = [a for a in agents if a.parcels > 1]
        tot_needed = sum(a.parcels - 1 for a in need)
        filled = hired
        for a in agents:
            if a.parcels >= 1:
                a.add(R, exp)                      # su propia parcela
        wr = w / p                                   # salario en raciones
        paid_workers = workers[:hired]
        for a in need:
            share = (a.parcels - 1) / tot_needed if tot_needed else 0
            n = filled * share
            if wage_in_food:
                a.add(n * (R - wr), exp)               # el jornalero se queda wr por parcela
            else:
                pay = n * w
                if a.coins < pay:
                    n = a.coins / w; pay = a.coins
                a.coins -= pay
                a.add(n * R, exp)
        for a in paid_workers:
            if wage_in_food:
                a.add(wr, exp)
            else:
                a.coins += w

        # --- Mercado de raciones ---
        demand, supply = {}, {}
        buffer = 2.0
        for a in agents:
            have = a.stock()
            base = 1 + buffer
            extra_want = a.beta * max(a.coins - 5 * p, 0) / p if p > 0 else 0
            if have < base + extra_want:
                q = min(base + extra_want - have, a.coins / p)
                if q > 0:
                    demand[a.id] = q
            if have > base:
                supply[a.id] = (have - base) * 0.8   # vende la mayor parte del excedente
        Dm, Sp = sum(demand.values()), sum(supply.values())
        traded = min(Dm, Sp)
        if traded > 0:
            fd, fs = traded / Dm, traded / Sp
            byid = {a.id: a for a in agents}
            for i, q in supply.items():
                g = byid[i].take(q * fs); byid[i].coins += g * p
            for i, q in demand.items():
                byid[i].add(q * fd, exp); byid[i].coins -= q * fd * p
        if Dm + Sp > 0:
            p *= 1 + 0.3 * (Dm - Sp) / (Dm + Sp)

        # --- Comer y morir ---
        for a in agents:
            eaten = a.take(1)
            if eaten >= 1 - 1e-9:
                eaten += a.take(max(a.stock() - 2.0, 0) * 0.5)
            if eaten < 1 - 1e-9:
                deaths += 1
                free += a.parcels
                a.reset(day)
                a.coins = respawn_coins
            else:
                a.score += eaten
        # Caducidad
        for a in agents:
            a.food = deque((q, e) for q, e in a.food if e > day)

        money = sum(a.coins for a in agents)
        food = sum(a.stock() for a in agents)
        owners = sum(1 for a in agents if a.parcels > 0)
        log.append(dict(day=day, players=len(agents), price=p, wage_r=w / p,
                        money=money, money_pc=money / len(agents), food_pc=food / len(agents),
                        owners=owners, deaths=deaths, land_price=rent * 75,
                        maxparcels=max(a.parcels for a in agents)))
    scores = sorted(a.score / max(day - a.alive_since + 1, 1) for a in agents)
    return log, deaths, scores, agents


def report(name, **kw):
    log, deaths, scores, agents = run(**kw)
    print(f"\n=== {name} ===")
    for d in (0, 7, 30, 60, 90, 120, 179, 270, 364):
        if d >= len(log):
            continue
        L = log[d]
        print(f"día {d:3d} | jugadores {L['players']:3d} | precio ración {L['price']:.3f} mon "
              f"| salario {L['wage_r']:.2f} rac | dinero/jug {L['money_pc']:.0f} "
              f"| comida/jug {L['food_pc']:.1f} | propietarios {L['owners']} "
              f"| máx parcelas {L['maxparcels']} | muertes acum {L['deaths']}")
    print(f"consumo diario medio: min {scores[0]:.2f}, mediana {st.median(scores):.2f}, máx {scores[-1]:.2f}")
    return log


if __name__ == "__main__":
    report("A. Base: salario en monedas, entra 1 jugador cada 2 días")
    report("B. Salario en raciones, entra 1 jugador cada 2 días", wage_in_food=True)
    report("C. Salario en raciones, sin registros desde el día 60", wage_in_food=True, stop_reg_at=60)
    report("D. Salario en raciones, 1 año, entra 1 cada 2 días", wage_in_food=True, days=365)

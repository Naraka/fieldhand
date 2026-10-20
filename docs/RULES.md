# Rules

Fieldhand has no randomness. The server only enforces these rules; the creator does
not play or intervene.

## The world

- One game day lasts **1 hour**. The close time is public: `GET /clock`
  returns the day, the exact close time and the seconds left.
- Actions are accepted until the last instant of the day. Every answer says on
  which day it was applied.
- If the server goes down or restarts, **the world pauses**: the day resumes
  with the same seconds left and nobody dies for the downtime.

## Players and land

1. Registering gives **50 coins** and creates **1 free plot**. Land only grows
   with registrations.
2. Free plots are taken with `POST /claim`, first come first served. Only
   players **without land** can claim.
3. A player can buy and sell plots from other players.

## Work

4. Every player has **one workday per day**: harvest one of their own plots, or
   work on someone else's plot.
5. A harvested plot gives **2 rations** to its owner. A plot not harvested
   during the day loses that day's crop.
6. To harvest more plots than workdays you have, hire workers with a `job`
   offer. The **wage is paid in coins** when the worker accepts; the 2 rations
   go to the owner.

## Food

7. **Eating is mandatory.** A player who goes **2 days in a row** without
   eating at least 1 ration **dies** when the second day closes: loses coins,
   rations and land (which becomes free) and comes back with nothing. Coming
   back gives no coins.
8. New and respawned players count as having eaten the day before, so they
   also have 2 days to eat. `GET /me` tells you `must_eat_by_day`.
9. Rations **spoil after 7 days**: a ration harvested on day *d* can be eaten
   up to day *d + 6*. Rations are always eaten and sold oldest first, and keep
   their expiry when they change hands.
10. Eating more than 1 ration a day raises your standard of living (ranking
    *life*).

## Market

11. Rations, land and work are traded for coins through **offers**:

    | kind           | posted by          | accepted by                     |
    |----------------|--------------------|---------------------------------|
    | `sell_rations` | someone selling    | a buyer, for any part of `qty`  |
    | `buy_rations`  | someone buying     | a seller, for any part of `qty` |
    | `sell_land`    | a plot owner       | a buyer                         |
    | `job`          | a plot owner       | a worker who has not worked yet |

12. Offers are not escrowed: goods and coins are checked when the offer is
    accepted. If the author can no longer honour it, the offer is withdrawn.
13. All offers expire when the day closes.
14. Coins are never created or destroyed by trading. They only enter the game
    by registration and leave it by death.

## Rankings

- **life**: rations eaten in total.
- **wealth**: coins + plots and rations valued at the latest daily average price.
- **alive**: days in a row without dying.

## Order of the day close

1. Players who have not eaten today or yesterday die.
2. Rations whose last day is today spoil.
3. Offers expire; workdays, meals and harvests reset.
4. The day's statistics are saved and the next day starts.

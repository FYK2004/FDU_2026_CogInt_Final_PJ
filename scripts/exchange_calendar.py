"""Regular NYSE/Nasdaq full closures; early closes remain trading days.

Reference: https://www.nasdaqtrader.com/Trader.aspx?id=Calendar
Exceptional closures require updating this calendar.
"""
import datetime as dt


def _observed(day):
    return day + dt.timedelta(days=-1 if day.weekday() == 5 else 1 if day.weekday() == 6 else 0)


def _nth(year, month, weekday, n):
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(weekday-first.weekday()) % 7+7*(n-1))


def _easter(year):
    a, b, c = year % 19, year // 100, year % 100
    h = (19*a+b-b//4-(b-(b+8)//25+1)//3+15) % 30
    l = (32+2*(b % 4)+2*(c//4)-h-c % 4) % 7
    m = (a+11*h+22*l)//451
    return dt.date(year, (h+l-7*m+114)//31, (h+l-7*m+114) % 31+1)


def exchange_holidays(year):
    memorial = dt.date(year, 5, 31)
    memorial -= dt.timedelta(days=memorial.weekday())
    days = {_nth(year, 1, 0, 3), _nth(year, 2, 0, 3),
            _easter(year)-dt.timedelta(days=2), memorial,
            _observed(dt.date(year, 6, 19)), _observed(dt.date(year, 7, 4)),
            _nth(year, 9, 0, 1), _nth(year, 11, 3, 4),
            _observed(dt.date(year, 12, 25))}
    new_year = dt.date(year, 1, 1)
    if new_year.weekday() != 5:  # no Friday observance for Saturday New Year
        days.add(_observed(new_year))
    return days

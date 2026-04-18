<script>
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { authStore } from '$lib/stores';

  const { children } = $props();

  // Bull image shared with public layout — embedded as base64 to avoid file-serving
  const bullSrc = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAARQAAAD+CAYAAAD72PopAAAoc0lEQVR42u19T0wb59b+M1V3+EJ+i0+QBQ0Nl26SLxB2H0iELIIUWADZQBd2uCpqQlpUIgFZJFFchSwCSHFFy58qVQleFDb8WYRIZBGDBHfn4pRsyiVfEhYE3cWHe531/BaeIa/H74zH9oznnfF5JJQwmD8ee5455znnPAcgEAgEAoFAIBAIBAKBQCAQCAQCgUAgWA9ZlutkWV6WZTkiy3IPnRECgZAPobyRP+JIluUTdFYIBEIuZNIjpyNIZ4ZAIORCKBEOobyhM0MgEHLRTvTQYdXv+YRONYFQFBgw+FoHnR4CgWA2OjkhG+OIIhQCgWBFdAIAZbIs1xGhEAgEM+hhP9nZ3cP80zXtY4hQCARC5lIxgFPssfYbg1jd2NI+tIoIhUAgZJXubEZj+CvxAe8O3msf10yEQiAQjKKTZgC17DE1Mnm1+9qW30mEQiB4F0Htgc1oTO+xpKEQCATd6KQDwAX22P7BoVFkUkaEQijGWZSILMuzsixX0RkxREh7YHph0fZf+imdd4Ib2sYBzDJ6wAUkRUQiFf75CkJT2QHAKxWDNBRCMZY9f9eKiwBOKaIjIZ187/HI5K/EB6NvjRGhELx+cYQA/EpnwnyLvRLJpWH0cTjTtx8RoRC8Hpl8R2cC2eom2kgOMwuL2H9/mHKs4fw5IhRCUfVPUGSSvW5yVXs8nkhwo5PPTpZrD20ToRC8GrYv8y4MgmE0d4/3tf7741ztpLG+lgiFgGJpxirTNmMFhoO8xzYTmchBvWhu/umanqXP7NhKKFQ2Joh0cVSBo5v03x9H6d9K6ASlR3IhXpoDJCeK+0fGud97puY0KlNTnreSJL0hQiHA674do4/DSUHxPWxrF/dAX04ambTfGNT9/i/bWrSHIqA+FIIH0aHVTWaY7k7OHEpdETqvBcHvywGQbK8PDAcNe05amxq1h5aJUAhevOumdHc+W99KuTA2oy/BaW47UUTC6zZ0xFc1MmkOXE8rEbO43NSgTXfikiQRoRA8h2btgd80reKrG5tFZ7CszC+9QVJ4PaX3uNWNLbTfGMzUDYtrXZ3aQ7OgWR6CB5EWaWz9nhqRvNp9jf2DQ+0dtsPqi0IQcbpH+Thl9Fi1z+TnhaWMP7fh/DledScEmuUheBB1Znw7fksfcGv3wuSxLMtVsiwPyLK8DeB/ldTGkEw2ozFc9PeZIhMA+PHukPbQE6uqO0QoBOEjFOj0ViCDCbOLBNYOWZZDDIk8go7YCo3w2n5jEB3fDBnqJSyGvvJrIzuAY8BEKQ+hqLD//hDzT9fQnVr6vCfL8qzVd1sbRGf1o9kMcfAikpmFJd1mNT2cqTmNa91p2skPdpwvIhSCKIhA4zCmh9uhKVy+0IAynw+a0medIPpHFePXUmX2eelFI789XcP80zXT0QiLUl8Jfrw7pD1Xb+2ITohQCK7EX4kPGH0cxoOBPvZwrRKl9BSQNOqUVK1Z+bc2358dTySwGX2JzWgMz9a3ciIRFg8G+nC2pjotRZQk6YgIheD1COXex2nYCsMH/7ywhMb6WrQ2NbCHryoXe4cVF4wy9cySR5UVpMGmMPsHh3h3cIid3T3s/LmXN4Gw+LqrU5saqqlOxK4XUaL3MUEgnUFmP/+v/2nJGM6vTI7z7sBxJMuhIbPEopBHM6NznLKKNOKJD0myOHh/TB6Z+kXyRXfrJUykV3VikiTZmhYSoRBEIpRlAO3q54FbwYwCZKmvBJG5aV4FQ8UKkh2mEU5VqTlXgRScLtWdP/fw7uDwOPKwMtqwgkwANNuV6hChEERtL/+VLRHrTcyajFRsQTyRwM6fe8daRyEiDrMY+sqP4V4/L2JrliRp2+7fT4RCEI1U3qjpRjyRQH2n39TFWuorwdzDIK8TFFYKpZvRWE5b90p9JbaSTqmvBA8G+niaScHIhAiFIHyUMrOwiDuh6Xzv0Mi2VKuSx2b0pSWpy5OHQczML6aNE1iBMzWn8ePdIT0tqWBkQoRCEJVUImB6N/rvj2F+9XlWF9hwb0BbAYKRcLqzm0xhrK60aIku2+eSKSq51nVFj0ALopkQoRDcMhy3DcYKcvRxGGO/hLP6OZUV5bh8oQGN9bUo85WkCah/7O7ZtjScR3KRuemcnws4wutwb0BPjF6Bjb0mRCgEt/qjRFhS2T84xPTCoiUNX04guhg+JgCzgnOWRAIANyVJCjn1HIlQCKKu0ehB0pqgTE/neHfw/rgVv1CRhpXl3Pmna7gdmjIl1pogkpgSlWw7+RyJUAgibr5rh80zLiJEKWr69e39MV1CNEEkcSQb+IIiPD8iFIJIZBKBQZNZPJHAs/Ut/PZ0zZZqiYNNZ5h/uobVjS3E/5PAZyfL0VhfyxuA1OIJgKBIU9ZEKAThyWQzGsP80zXLqiNOotRXguhSOBNRZIJwRAIaDiQIhFkemcQTCQSGg66NRqAzKT0zv5Rrr4ywREIRCkEkAfYFdHbLiNLS7mCUElMId9aJMjDIApIA960eTYtMvEombJSSgURuAvhckqQ6SZJCbiATIhSCCA1saW5mmRZVeQEcb9wYgH8A+H8Mibxx2/MiQiFAlE2BQFKA9ZJmggzeuAxqAUTcEokQoRDghuVeo4/DRfPkOc816PbnRIRCcBJV0GgnxRCdsFGKZv/QVbfvGCJCITiJ2tR052XRnQBOlBIiQiEQLMDOn3tF95y3fn+Jnd097SbEZiIUAoGQE2bmF+EVLYUIhUBwGPOrzxFPJNhDF9wapRChEJxEjE6BGqUseSJKIUIhOIk37CeN9eeKl1AW0tIeV0YpRCgEOLwtkCGUWpQyVo0osvWqnO7ZIBEKgWAey9oDnDUQRYNpD0QpRCgEx6DMqqyzx4Z7/UUbpbzafa1tdHNdlEKEQoBI08ZlPh/X0axYwEl7XBWlkB8KAaLt4cnHFd4L+NfzRa1XyrokSc0UoRAI5tCDpNkyWC3lycNgUaY/bo5SiFAIomgpA9rjrU0NWJkcR2VFOYq8J8U1WgoRCkEUUplF0jM1BWdrqvEiPIUzNadRTFPIqxtbvCiljgiFQDBPKj08Uinz+RCZm0Z366ViTnvAi+JIlCUQkFGknQVwVe9CKxaxVrsUTMHnIltDUoRCcE2kAiTF2hdzU0Uh1v7Gj1KClPIQCLmRyk3e187WVCO6FEbD+XPFmPZ0KIvRiFAIhCxJJQTgPIC34OgqK5PjGPrKjyKyiISyPH6ACIVAyI1UtgHUAVjhfX2414/ln8Y8W1rWiVJ6iFAIhNxJ5UiSpA4AnbxopbG+Fi/CU7jc1FAM5ksAcEqW5R4iFAIhP2JZVqKV73kp0NzDIEYGrnvueT9b33JNlEKEQnBjtBIE8Dk0k8oAcK3rCr7u6oTHbQ0AQRvdiFAIrm3XVwbmLkJjJTnc6/ecrcH+wSHc0OhGhEJwO7FEJEmqA/ADm/54raSsE6VcFa2ETIRCgAc6a3u0moJm1w08qqNANC2FCIXgBTL5VenPAACsbmzhr8QHeK0nRYckB4hQCATrZn5+Rdp6zzkUyUIwIFlCbiZCIRByJ5ITsiwv8wYIRx+H8Wr3tSefN8fSQLi0hwiF4DoyQXL9RntaWnBwyNtvAy+t2tAhFWHme4hQCG4ikzokl4PV8r7uv3XPc9oJ0sTZTd7hMgAdRCgEgnky6VAikzLe172c6rgp7SFCIbiBTAYALOmRyc7uHsZ+CaNYNgzqkMoFWZariFAIhMyVnEdGj/n2/lhRnROdtAcipD1EKASRKznb0LGCVHE7NJV3qnO5qQH/er7oGs9ag7RngAiFQOCLr9vQEV9VbEZj+HlhKf87/sYWnq1vYeLukCtIxSDtOeX0wCARCkFU8fWU0ePiiQT671tnVn07NIWd3T1M3B1yhQucQdrTQ4RCICTJJAgD8ZVF//1x7L8/tPSuHxgOIp5IYLjXj4k7g25NezqIUAiklyTF13tmHj+zsIhn+hcU8pmXab8xiHgige62FqFJ5a/EB57frONpDxEKwWkyqVJSnKtmHr+zu4fRx2FbvUfcQioiRilEKAQnyaQZJsRXMLrJt/fHbO+GfbX7GoHhIAAITSoGlgZEKISibFZ7ARN6iYo7j6YK1g279ftL9Cv9Ld1tLVj+aUy45WL77w/1nNxqnWpyI0IhOKWXPEKW6yTmV5+j0I7zKqk01tdiZXJcOFJZ3RCryY0IhVDo/pIITOolYHQTp/YZz68+P9ZsztZUC0cqq/ppTzNoWTrB4/0ls9mkOEBSN7no77O0RJwLJu4Morut5Zjg2m8MCjPZ/K/niyjz+Xh+uxJFKAQvkkkIBv0lm9EYmgPXuVWLwHDQcTIBgP6R8eO/72xNNeYeBoU5v5vRl0YkToRC8JReEgHwHQw6VDu+GcKr3ddpfRW3Q1PY+v2lMM+n//7Ysa9rY32tMNUfg67ZZiIUgpdKwm8AXOB9ff/gEM2B68ezON2tl/BgoC9FhLViTgcWN5O13xg8rqyIUlLWi1CIUAhFURJe3dhCc+D6cQm4u/USJu4OgRVhb4emIGqHqv/WveN9wyKQSoby8QkiFILbzaN1S8Kjj8O4eit4LGhqySSeSCAwHBTaypFtfBOFVHTa8AsepRChEKy2HGiHTrWm/cZgirOalkwAJFMKAURYZNH4ppKKk9YHBm34RCgEV6Y4v0PHcmBndw/1nf4UgXXizmAamfTfH3OVL+z86nPMP137+Jwc9FOhCIVQFCnOzMIiLgb6UlIYtqeDTYUK3QkLi8rJ7MU8cXfIkb3KfyU+6G0WLKiOQoRCyHewr13fAGkMd0LT0GsQYys6bjaZDtwKpoiic6NBnKk5LVKUUkeEQhDdCOmFUYrTfmMwLeLgkclmNOZYW71dlZ8ynw/hh98XvEVfhPIxEQohK+8SpVHtnpE42H5jME0L4ZHJzu4eAreCnjg3r3Zf486jj6XuypPlBZ/7EUFHIUIhZDOLsw2dRjVeSdiITPYPDoWah4ENIu3ZmuqUZj0HdRRKeQhCCa+Gszi8krARmcQTCc+uDVXNrsGUk7/u6izY79/5k0soZYXyRyFCIZixG/jOyFrgor+PO3OjRya8lAge2uz37f2xYz0FAB4M9OFyU4PTaQ8RCsFx4fV3GNgzqiVhbSNaqa8ETx4G08gEgKfJBDp6SrKcPIjKinLPC7NEKISshVe9krBKJiuT42jl3JHd1rgGC/WUMp8Pc6NB20Xa/feHKdERCqyjEKEQshJe9UrCLJmcranmkokbG9eQp57C9qcUSqTV0VFOEKEQCt3xarhka/7pmm7KcqbmNJEJ+HoKi0LM/OikPReIUAiF9C1pz5Ti9I+McyszRCYwHCKcWVhMOTZys89WPUWndIxCVHqIUKgcbLjKwijFAYDLTQ1YmRznepoWO5mouBOaTrnIVT2lwCkPUIBKDxFKcc/hfIcMqyuMqjJfd3Vi7mGQyMQEtKnP2Zpq25ayOynMEqEUb1RyKtcUB0j2mOgJjEQm4JaStanPcK/ftslkp4RZIhSKSrJKcUp9JXgxN8XtMSEyMcbo43CaVeOPd4dsKSXrCLMUoRAKE5UAHxvV9FKchvPnEF0Kc8VXIhOYqvpovXIrT5ZjuNf61Gf/4D1FKARnopJ4IoHArSC3UY3VS/TEVzVFIjLJjGcbW2l2jde6rlie+rzjm1afoM2BhJyiEgDBTEQCJO0G+u+P6Wolpb4STNwd4na+FsNsjh2orCjHi/BUCjnvHxyi/oq1kcq//7lW8G2CFKF4t9s1Y1RyOzTFtRsA018SmZsmMrGhCjMzv5SW+lhd9dGp9FDKQ8i62/VUponUi/4+w0VaX3d1IjI3jcqT5dBb1EVkkjtmFhbTBNrhXr+lDW+8So/d/rJEKN4gkx5k6HZlo5KOb4Z0V1WU+kqw/NOY4czJzu5eyqIuAnISaEcfz6Udn7g7aKEwe1jwSg8Rijcmg3+FQber2ajkclMDokthNNbXGv4crzmtwcGJZO1F31hfa5lAqyPMUspD4KY3QQD/iwxDX2oFJlNUMjJwXbfrle2c7fhmiMgE9nXQAsneFBtLx0QoBK7oei/jHfDpGuo7/YblXHWw71rXFWQaxXe7Oz0EHR7UuqxVniy3xDaSIhSCYU+Jkt5kFF3Vblej1nkAGPrKj8jctG6jGhvhGKVKBOTdQavFcK8/7w5aJ+Z5iFDcoZMsI9npaiq9uRjge7yyfRDLP41l7NBUy8LUsFb4KKXM58sYNcLE/BAK3NxGhCI2kcwqOkm7mbtcpvQGSJaDX4SnDIVXdh8xVXKci1KudXcWfFkYEYq3ieSqWZ1k7JewYXqjGkc/GOgzFF7Vn6ndR0ywP0rRVnysiFL2C6yjEKGIp5GYIpLNaAz1nX70j4zrVm+gKQe3mljloNoWEJyIUuYsj1LeFbjSQ4TifPl3QJblN2Y0ErYPxKgMrI1KMpWD1TtZc+A66SUQqy/FiiiFCKU4opFZAP8H4BEyVG1Y97SOb4YMBVcwVgNGczhakjLb+dpw/hzO1JymF9Em/PZ0zdVaChFKAbfwybIcYqKRq2a+T9VI+kfGTRGJ2qS2MjmuO4ejFQOzaVYb7k2Wmgu5XhNFNuOjRZnPp2toRRpK8UUiKon8juQE8Ckz/QNq1caMRoIsm9Qy7SM21ljGj9drTtwZpBcZ1s/4zHOilOs5pj3viFBcH4UMyLK8LMvykRKJmCIRIFmq7b8/hr9fuoKxX8KmiQQw16SmFXTNRDzc0XvlLtrd1kKkUqC0p/JkuVX7fCJ2/u2f0suXl4lRHZI7Y9V/y5BDN+Oz9S1MLyzm1PNRWVGOudGgKSIBki30+Xa9jj4Oo7utJSUUp8oQLC8ha1PW7rYW4UVzIhQTfSFI7jOpQ7LLsFn5/FQ+P3d1YwvP1jfzeoN0t17CyM3MfSVq9POtRbuFk6P34WOLAyIV67G6sZmWujbW16KyojyryJUIxZ4owgjNSF2EVIWPMw9l1r5JkiSyurGVV9NYJltGcIS+0cdhSxvVfl5YwpdtLceRUXdbC0r/5jO0kySYx8z8ElcLu9bdaej96zQkj5sOBfONJJDncNZm9KUlJAJGeA0//N5UBWf/4BDf3h/LSSsxg4bz57AyOc4dTCRSyR8v5qbSUtl4IoG/X7qSlbammdn6XJKkNxShZOf0PusUkezs7mEzGsPq+pblF3I2KY4dUQkv11/d2EqJlM7WVGNlcpxIxYqIdn0rjVDKfD5cbmrAM41zvukIwkYy8RShKOnNLEwM0sHShUoxhUSSE6N2XUSXmxowYcJ4JzlxPJ7zGy5b3Hk0lZZ6EalYp6PwJsJb8yAU0lDMmw7NWq158Mhj/+AQf+zuYefPPdtSCb5mMmgqOgoMBwsq2u2/P8To43DaG59IBZasL+VVey5faABGcvqRMSKUzFFJCCa7Ts2SBrvKUSURJ5X1ibtDpiaEnaqyzCws4su2lrQ3PpGKNe9HbZdsNmlP2d9SWvaPiFCMy7nLAGqzjTDeHRxi/+D9cReh04SRKdXJVM2xorcEFji481IyIhXrCSWbtEejwbwhQtEXXpczpThqmfaP3T1XGgWZSXVEWQE6v/oc3W0tXOMmIhXLl55nNMjSARGKTjn4VyMdYWZ+0bIyrZMwSnXiiQQCw8GC6Tgw2UG7Mlmre6ckUkFOGhVPR6k8WZ5Lk9sbmuUxSSb7B4cI3AriYqAP86vPXf+mbTh/LuMKUJHIBEiWkXmDbSypROamyf4gS/yxu6cTpWTe3/PZyQoilGzJZPRxGPVX/MKW0nJJdfR2s4i+T3j0cdhwp27lyXKsTI4TqSC/laJm0x42spEkKUKEYkAm8UQCgVvBrEfwRcdwr1+3E1b0fcK8ReDg+HsQqWTXLJmJLEzgLci+wJhM2m8McqMSN79RG86f0/Uz6bdouM9ujP0SzmjsQ6RiHvH/JHKKUDQrTd8UPaEo1Zxfswn7VZMhr6U6olRzzOJ2aIqbDrHHVVKxyOcDXrYzgMFsFwTwQRGeUGRZrkOyNJyGwHDQkEz0ck63pjozC4uuM49+trGVtrxqMxrDzwtL6Gf2+Zb5fJi4O0SkkiOMGh41Ecx20RIKM5dTxrtT8xhbJZMynw+rLhRn9VKd+adrQo+rZxOlqNHX/OrzFFIBkiVy8qnNXkc5+0W12S7Z7WKOUELgdMDeDk1x79QsmQDAs3X3EQov1dnZ3eOmDnDRLAprulx5shxDX/l1SYV8arPXUYwiFKZL9q3dU8bCEooy6HeVd6fmtZeruoN6Ynd294R2tIKOZ4U21VEb19zeT6MtI1/r7kRlRbkuqXS3teDJw6DrVnCKCCZ62UYxmlQzqU5a7s0bfCv1lWBlcjxlXkGbt4uOMzWnuSPqhZ4ahq1zPuGUO+rIzb6Ulv3ArWAK6bQ2NWBlcpxIxYyG8rcSXa9hJnqJFKvrfZpusrO7h8CtoCkyAfiO4W5LdW6HpoTrgkWedpFsGbm1qSGlpPlsYwvtNwZTSIW6ak1GITrm5JqIt/gIRUl12rVh/7ccj1I9Mtk/OHTVEODQV/6057C6seXo5LBd+FaT2vx4dyglAnm1+zqNVNSuWk0/BcEEmApPXJKkokx5QuC4gWkJQo9MVIcrN6c66l4eeLSXgq2+VZ4sT6tq8UiFelWQ4zTyMQkvo9gWfcmyHITGA3b+6Rq3ojP3UH8Hjd7JFRHqCopM0ZiXcOfRVFrfjTal4ZEKkCwrUwUIphskmQglUlSEogixA9rUhVcunbgzqNtuHE8kXDMc+HVXZ9rz6L8/7krPFuRgF5lJQ3q1+xoX/X1pvRfdbS14MTdVlGJtNv4nmscWXYQyoBVieXfqiTuDhguj3dJ7UllRnpbqzCwsemZSGibsIrXiq9qboiWf9huDaaRCYi0yNrwxthcrkiQdFQ2h8KKT+adraRUODpnEAfzA84KF8KZJgynNSJvRmGs7YZFjGdlM6qM+lkcqlSfLEZmbLhpdxYg8eQ1vly80OJLuiBCh9LDRSTyRSAuJOWTyFsltf0fa6ojbUh3VFKrYML/6PO0GoDcU+VfiQ9I0i9MOoOoqXk+BNCZJMBoc7G69xN6wlouNUAa06xfZZi4OmcQA1CllsA6WTEQXM0t9JWmpjv/WvaK1Q9TeOPRSHxX9I+NcUulua/G8DYJeEYJnEcFcLyuFarcXglCUvpNT2vyaZVoNmTwB0CxJ0pHieF/7UT/ZdJ0/rFu8TVBAu0i91IclFV5ZXfWr9WoKpGf1qI3yKivK2Qh42Ym/1ckIpUOrnah36+7WS9qVDE8kSephBKYON5WLtasw9ErixRilaMvDP2bYjji/+pxbVlZtELw4B6RX4dESyrXuTlZjLB5CUcTYlAHAaSU60SMTjvYCQPxhQO0qDLdPEMNmu8hMqY8a3fDEWiBZ4YguhT3TXWv0PNgbaamvhI3olwtd3XE6QungtcybIROFjGrdMrvzYODjcnOvTBDDZrvITKkP8LEBjlfdU7trRwauuz5aab3QoFsuZm+krU0NbEodcurvFYJQVjc2zUYmad8rcv9Jw/lzKTqQVyaIUQC7yB9NLIb/K/EBHd8MpWhvKSlA1xVE5qZxOcPmRaEJpamRe/y3NP0poP43VsjZHVEIpR0c0dIEmaQQisgrRLX+sKOPw56aIIbNdpFmUh8Vd0LTaRYIYHpW5h4G8eRh8NiHBS7qP9FztmdvpJebGtjHhZz8mz9xyHg67U7CYF2PTJR0p90Nw4CsP+zqxpbnVn0UIkoxk/qwpMRr12dTghfhKdMkJQKu62w/0KY71z5aZ76VJGm2qAgFyaY0PcS0KY3R94qqn7D+sF6eIIbFdpG8PhMzqQ8r8l4M9OmmQGU+H4Z7/Yguii/alvpK2I5X3XSn4fw5tgoUcvrvFolQ4gA6MqjTHWxXrah9HOpFUAwTxFZHKdq0JZvUx0wKxPqsLP80JiyxdLe16PrFsunOlx81ujg4bofFQCgX9MjCRGdfh+hiLOsPy/NzIcC0XWQuqQ+bAtV3+g1HMhrra7EyOY6JO4PC6St66Q6rG1ZWlLOif8ipUrFjhKLs2uHh+0x7V5XO2jKRZ3dY0yQ37tKBgHaRuaQ+LEFdvRU0jFbUaCC6FBaGWLpbL+mKsaxu2J0anYREeP0KHaFUcY6tS5IURBalZlG9T9Q3fbFNEMNmu8hcU59sohWWWJxMhUp9JSkm3jBYnM50xgZFiE4AQHLAme2eRjepMzPEJMvyGyizP6sbW7gq2JTu0Fd+DPf6EU8kUN/pJ90kTyz/NMZtOW+/MZhX+f1yUwMeDPSZWjS+s7uHmfnFgg6fqu8jI+wfHOKP3T11nCMmSVKdKK+b04TSKUnSsslU6XcIuue3sqIc0aVk7t8cuE66icXnVHsxNQeu53WBl/pKcK3rSsYLNyUiXt/C9MKira+t3nPOgIuZ5AIvpzzLSPqZAMnmteUsfFOE9T5RZ3WKfYIYNttFqhUas0RgpK2M/RJGfafflDFXmc+H7rYWROamEV0MY2Tgui12CXOjWUfd34tEJgWPUPKIbIRNd77u6sSDgaQBEG8ZGSE/PSG6FOaWT/NNfaDpGxru9Wfl26pGS6sbm1hd38r7b8lkcQq+9tgs2msmuYBMUtKd26EpYfbWVFaU40V4CvsHSf9T0k1gS8VjglPhsSL14f2u4d6AKX0FOnYCm9GX2IzGTBNMqa8EDwb6siWTmOoNRISSPaEMAHikfl7f6Rdmfmf5pzGc/aIaF/19NPRnI17MTXFdy2YWFm2ppuVLLGBE3Z0/9/Du4JCbWp39ohrXu65k+3uEJRO3EMo2FLuCnd09XAz0QRTTpLmHQUtDb4J+SrIyyU8n7Tz/uaZCNkJoMgHE222sJZMqkb1PaIIYjtlFQmelqdW/t+ObITQHrmP+6Zphc1wB8L0kSXUik4nwEYo23aGSLIq6jPwiPMUVaO1KfXh6R2tTA651X9E1jrYYqpVj0AnDaS8SyrJqV7B/cIj6K366sooYRk1fhU49z9ScxpdtLWhtasxbazm+GCVJYuw93riFRFxBKIr3yf8V+i5EgNBl5MjcNPcCtqPqky25NNbX5hu5XBStr8RLhNID4FdKdwjgiOHQWXPq9E0nucoi6VFy+UKDrgUBEYqD6U48kcDfL12hq4kAGMz5OJH6mIle/rumGo31tWisr82UHv3Dacc1LxOKDGaPDXWhEtiLNDI3rdu96lTqYzaC6W5rwbXuTl708r3JyXtQ2Tj7rYJw095iAhy3i1RnfSZy8E5BAWeUxn4Jc5eVeQGi9qF0aP0sCARksIsEY0gt+uqMV7uv05acwdhvmQjFCkJxOjqprCjH0Ff+4w+vbKSDB+wiORck2Alw0Zd8mZl0BmkolqzZeAEBvE9GBq5rV3wA+OiPsRmNFdR8h5CO6GLYwC5RPCMuLf79zzXhJ4jdTighAN+pn1df6nTkgs1mnFwllmfrWzQkCHHmfAAgcCsodMqsIRRIkiQRodjkfbIZjaHjmyEROjLjACLgbDyEjR4ZBORdRhbdkpMIxePeJ5ySZBzJCc9tZVixR/k4BRPWgZvRl3i2vkmpEeCYdaLIqQ8RSgHTHSe8TzjeG9zuRUXr6UFSQC6DSX+M1fUtrG5sUtcvCqN3iZ76aAnF7d2yEnmfGKY6GTsXlZmjDuWj3ezvImEXBbOLFDn14aRrriaUT0T1Plkt8GbAyopyds8JkDTRnjUxIXokSdKsJEkdAD4HcBNJIxyYMT6euDuEvedLeDE3hZGB61SWRu5l5DuPpgzPt8gNb6DGNtjazMZuSEOBnOuZu1tMkqSeHMbP30iSFFL2pJgmFyC5yOpa1xWsTI7j3/9cw5OHQXzd1WmLu7pXMb/6HDu7e7pfd0PDG4ATpKFYnO4U2vtEda7XirAWR18diuaStZ8gK+5uRl9SaRq5l5FFS304KY+r53k+ETLdKWB0UlmRtuclaCWZGEQu62a/v8znQ2tTAybuDiG6FEZ0MbmHt7v1knBLviGAXaRRdzWlPvbiU0H+juaUdKeA+snIzT421VmXJMnWpdOKC1cIQIgRdJuzqRZVnkxOrKqNd2oEk1zjECv6CtKdR1NorD+XksKyNyw19aEZMe8SSsoi9EI1hF1ualD3w6oYKGi+mTQcnlU+1D4clWAuZBvBsM9lMxo7XuPwx+6e50mmsqIcZ7+oxtmaajTWn0tzilfOcTurmQna8HaCCCV/q8fjF/pZgaKTUl/J8QpRJnfddvJcKL9/mzkvzcxHVtqLaugDzYjA/sHh8Z6YeCLhSqKprChH5cnypOXiF9XaaITVwkKqHqH0OLVrUx8BG97qiFAsre5sFaiqM8S+Cd8qaYgwUKKXZeVDJZg6hmAuZPszUwnGnzIu8O7gPeKJD9j5cy9lErbQpKOSBQB8drIclScrACSXYpX5SszsyOE6xUuSFJFl+QcwjZOU+niwyiPL8iyAq+rn//U/LXDAl9SV1ntKitSsEE1dLhUk5LANL/6fBKd68pGMtEgSQ7nO1yqsco2Pqemj3u4ahZQj7HlyuurDqfK4euL402LzPuGkOutu9fFkUyQNydQBqFLIpgom5o7MwsjVvbUwPR5x5TlvA3gDYNtsZ6kkSUeKG+C2KoALnPoQoeRo9Vj2UT+xv1z8YKBPm2976p3EIxlm9ugEQzZVVpONDaRxxBCHSh5H+VbZlI0KSyKkPvH0yIga26xKd+z2PuE0PT3JpSPWa2D0GSj/qm9qlXRYXMjhV7xVCIFFhPP/gi230g6iOpX68JaXuXni+FNR0p3NaMzWF7PUV4IfUxua4l6LTvIUgCOcC93Lz3lAidpqKfWB+ztllVy/rFD6yXCvXyv+hdy46pFgKXpcOOtDhGLmxbSz/6Th/DmtV4ZwZWKCY3rT93CZuTURSoZ0Z2d3z7aBN06qA6VH4YhefoLS+BajWR8XE4qS7pwqxOwOJ9VZd/u6RwKlPkQoMBgGtGm6mJPqAAWe1yFQ6kOEUsA7wv7BoS2t3Tqpzg9Oz+sQKPUxuZuKCEUk7xNOqvMWVCYmIKOuF2dTH7stOb223/gTx4cBbdBPdFKdHhJiCSa8alJS4h/vDtma+ujNPxGhCOJ9YpDqROiSIZgglVkAT8CYWTH2oASRCEVp8b5gZ+8JJ9WJUapDyBIDrJ7S3daC7tZLdFYEjFBs9T653NSgTXXilOoQchxFaGb1lJGbfbSBQGRCiScSlk53VlaUa20JAKCDqjqEPEkFQLLqE374PZWSBSOU9o/DgC8t1U3mRoNaW4J/kG5CsKA/5R+snrIyOU6kIgKhaGvrVnmflPpKsDI5rjX++Qd1wxIsFGlvgjGYWpkct2x9iU5R4ogIBdl2x24RmRDcQiohMJWfszXVeBGesqRHhafLuDlN/8TJXbTIU4CNLoVZMokDOE9kQrCJVHpYUinz+bAyOY6Rget5pUCfKSbcSK1KUspjAkfa6AI5iq9PHgYx9zBFM1kHUEUCLKEApJIy83Ot6wqiS2EMfeXPKQ261tUJAyc7soCEccv9sTnwzu4eRh+HTTm1VVaUo7H+HLrbWrQO4XEkrQjI24SAAr6Xe5D000nb9LgZjWF1Yws7f+5hZ3eP+94+U3Ma/11TjeHeAM/x/3M3G39JDrwQv2qPq3th2OqPuofFYM3CE+3uFQKhwBYcs7B2dckPkiTRNHy2L4QsyxE5d8wq0Q6BIES0IsvykZw/InQ28ywjK+Rg5sVYlmV5QGndJxBEJZbtHIjkSJblIG0OtD58PKEpLUcAHJHQSnAZsVQx62KrkFxLUsap5LyBsmqWRkMIBAKBQCAQCAQCgUAgEAgEAoFAIBAIBAKBQCAQCAQCgUCwCf8fyQ1s7789xbYAAAAASUVORK5CYII=";

  // All algo pages require admin
  $effect(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') {
      goto('/signin');
    }
  });

  function isActive(/** @type {string} */ href) {
    return page.url.pathname.startsWith(href);
  }

  function signOut() {
    authStore.logout();
    goto('/about');
  }

  const algoLinks = [
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/console',   label: 'Terminal'  },
    { href: '/algo',      label: 'AI Agents' },
    { href: '/orders',    label: 'Orders'    },
    { href: '/admin',     label: 'Users'     },
  ];

  let menuOpen = $state(false);
  const closeMenu = () => { menuOpen = false; };
</script>

<div class="algo-viewport">
  <div class="algo-card">
    <!-- Top bar -->
    <header class="algo-navbar">
      <div class="algo-nav-inner hidden md:flex items-center gap-1 h-16">
        <!-- Site label -->
        <button onclick={() => goto('/about')} class="algo-brand">
          <img src={bullSrc} alt="" style="display:block;" />
          <span class="algo-brand-name">RAMBO QUANT</span>
        </button>

        <nav class="flex items-center gap-0.5 flex-1">
          {#each algoLinks as link}
            <button
              onclick={() => goto(link.href)}
              class="algo-nav-btn {isActive(link.href) ? 'algo-nav-btn-active' : ''}"
            >{link.label}</button>
          {/each}
        </nav>

        <span class="algo-user-pill">
          {$authStore.user?.display_name?.toLowerCase() ?? ''}
          <span class="algo-user-role">admin</span>
        </span>
        <button onclick={signOut} class="algo-nav-btn">Sign Out</button>
        <button onclick={() => goto('/about')} class="algo-pub-link">↙ Site</button>
      </div>

      <!-- Mobile -->
      <div class="algo-nav-inner md:hidden flex items-center justify-between h-16">
        <button onclick={() => goto('/about')} class="algo-brand">
          <img src={bullSrc} alt="" style="display:block;" />
          <span class="algo-brand-name">RAMBO QUANT</span>
        </button>
        <button
          onclick={() => menuOpen = !menuOpen}
          class="algo-hamburger"
          aria-label="Toggle menu"
          aria-expanded={menuOpen}
        >
          {#if menuOpen}
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          {:else}
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/>
            </svg>
          {/if}
        </button>
      </div>

      <!-- Mobile dropdown -->
      {#if menuOpen}
        <nav class="algo-mobile-dropdown">
          {#each algoLinks as link}
            <button
              onclick={() => { goto(link.href); closeMenu(); }}
              class="algo-mobile-item {isActive(link.href) ? 'algo-mobile-active' : ''}"
            >{link.label}</button>
          {/each}
          <button onclick={() => { goto('/about'); closeMenu(); }} class="algo-mobile-item algo-mobile-site">↙ Back to Site</button>
          <button onclick={() => { signOut(); closeMenu(); }} class="algo-mobile-item">Sign Out</button>
        </nav>
      {/if}
    </header>

    <main class="algo-content">
      {@render children()}
    </main>

    <footer class="algo-footer">
      <span class="algo-footer-text">RamboQuant Analytics</span>
      <span class="algo-footer-sep">·</span>
      <span class="algo-footer-text">ACU-5195</span>
      <span class="algo-footer-sep">·</span>
      <span class="algo-footer-text">Admin Console</span>
    </footer>
  </div>
</div>

<style>
  /* ── Algo viewport ─────────────────────────────────────────────────────── */
  .algo-viewport {
    min-height: 100vh;
    background-color: #080f1c;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .algo-card {
    width: 100%;
    max-width: 1440px;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background-color: #0d1829;
    border-left:  1px solid #1e2d45;
    border-right: 1px solid #1e2d45;
  }

  /* ── Navbar ─────────────────────────────────────────────────────────────── */
  .algo-navbar {
    position: sticky;
    top: 0;
    z-index: 50;
    background: #0a1020;
    border-bottom: 1px solid #d97706;
    overflow: visible;
  }

  .algo-nav-inner {
    max-width: 1440px;
    margin: 0 auto;
    padding: 0 1rem;
  }

  /* Brand mark */
  .algo-brand {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0.1rem 0.5rem 0.1rem 0;
    margin-right: 0.75rem;
    outline: none !important;
  }
  .algo-brand-name {
    font-size: 0.72rem;
    font-weight: 800;
    color: #d97706;
    letter-spacing: 0.08em;
    font-family: ui-monospace, monospace;
    line-height: 1;
  }

  /* Nav buttons */
  :global(.algo-nav-btn) {
    padding: 0.22rem 0.6rem;
    font-size: 0.68rem;
    font-weight: 500;
    border-radius: 0.2rem;
    background: transparent;
    color: rgba(180, 200, 230, 0.75);
    border: none;
    cursor: pointer;
    letter-spacing: 0.03em;
    font-family: ui-monospace, monospace;
    transition: background-color 0.06s, color 0.06s;
    white-space: nowrap;
    outline: none !important;
    -webkit-tap-highlight-color: transparent;
  }
  :global(.algo-nav-btn:hover) { background: rgba(217,119,6,0.1); color: #fbbf24; }
  :global(.algo-nav-btn-active) {
    background: rgba(217,119,6,0.15);
    color: #fbbf24;
    font-weight: 700;
    border-left: 2px solid #d97706;
    padding-left: calc(0.6rem - 2px);
  }

  /* Back-to-site link */
  .algo-pub-link {
    padding: 0.18rem 0.5rem;
    font-size: 0.62rem;
    font-weight: 500;
    border-radius: 0.2rem;
    background: transparent;
    color: rgba(150,170,200,0.5);
    border: 1px solid rgba(150,170,200,0.15);
    cursor: pointer;
    font-family: ui-monospace, monospace;
    transition: color 0.06s, border-color 0.06s;
    outline: none !important;
    margin-left: 0.5rem;
  }
  .algo-pub-link:hover { color: rgba(150,170,200,0.85); border-color: rgba(150,170,200,0.35); }

  /* User pill */
  .algo-user-pill {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.65rem;
    font-weight: 500;
    color: rgba(180,200,230,0.6);
    padding: 0.18rem 0.5rem;
    border-radius: 3px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    margin-right: 0.25rem;
    white-space: nowrap;
    font-family: ui-monospace, monospace;
  }
  .algo-user-role {
    font-size: 0.5rem;
    color: #d97706;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  /* Hamburger */
  .algo-hamburger {
    padding: 0.3rem;
    border-radius: 0.2rem;
    background: transparent;
    color: rgba(180,200,230,0.8);
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    transition: background-color 0.06s;
    outline: none !important;
  }
  .algo-hamburger:hover { background: rgba(217,119,6,0.12); }

  /* Mobile dropdown */
  .algo-mobile-dropdown {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 49;
    background: #0a1020;
    border-top: 1px solid rgba(217,119,6,0.2);
    border-bottom: 1px solid rgba(217,119,6,0.2);
    box-shadow: 0 8px 20px rgba(0,0,0,0.5);
  }
  .algo-mobile-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.65rem 1.25rem;
    font-size: 0.85rem;
    font-weight: 500;
    color: rgba(180,200,230,0.8);
    background: transparent;
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    cursor: pointer;
    font-family: ui-monospace, monospace;
    transition: background-color 0.05s;
    outline: none !important;
  }
  .algo-mobile-item:last-child { border-bottom: none; }
  .algo-mobile-item:hover { background: rgba(217,119,6,0.1); color: #fbbf24; }
  .algo-mobile-active { color: #fbbf24; background: rgba(217,119,6,0.1); }
  .algo-mobile-site { color: rgba(150,170,200,0.5); font-size: 0.75rem; }

  /* ── Content ─────────────────────────────────────────────────────────────── */
  .algo-content {
    flex: 1;
    padding: 1rem 1rem 1.5rem;
    color: #c8d8f0;
  }

  /* ── Footer ─────────────────────────────────────────────────────────────── */
  .algo-footer {
    background: #0a1020;
    border-top: 1px solid rgba(217,119,6,0.2);
    height: 1.6rem;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0;
    padding: 0 1rem;
  }
  .algo-footer-text { font-size: 0.6rem; color: rgba(160,185,220,0.7); font-family: ui-monospace, monospace; }
  .algo-footer-sep  { font-size: 0.6rem; color: rgba(217,119,6,0.6); margin: 0 0.4rem; }
</style>

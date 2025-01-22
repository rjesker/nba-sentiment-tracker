# app.py

from flask import Flask, render_template, request
from nba_api.live.nba.endpoints import scoreboard, boxscore
from nba_api.stats.endpoints import ScoreboardV2
from datetime import datetime, timedelta
from pytz import timezone, utc
import isodate
import praw
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import re
from config import TEAM_ID_TO_NAME, PLAYER_NICKNAMES

app = Flask(__name__)

def slugify(value):
    """Convert team names to a slug for referencing logo filenames."""
    value = value.lower()
    value = re.sub(r'[\s]+', '_', value)
    value = re.sub(r'[^\w_]', '', value)
    return value

app.jinja_env.filters['slugify'] = slugify

# Configure your Reddit credentials here
reddit = praw.Reddit(
    client_id="your-client-id",
    client_secret="your-client-secret",
    user_agent="nba_tracker by /u/your-username"
)

def is_game_thread(title, home_team, away_team):
    """
    Basic check to see if a Reddit submission is a 'GAME THREAD'
    for the provided home/away teams.
    """
    return (
        "GAME THREAD" in title.upper()
        and "POST GAME THREAD" not in title.upper()
        and home_team.lower() in title.lower()
        and away_team.lower() in title.lower()
    )

def analyze_sentiment(comments):
    """
    Uses VADER to analyze sentiment for each comment,
    returns a list of compound scores.
    """
    analyzer = SentimentIntensityAnalyzer()
    return [analyzer.polarity_scores(comment)['compound'] for comment in comments]

def fetch_game_threads_by_team_and_date_range(home_team, away_team, target_date, local_tz="US/Eastern"):
    """
    Searches r/nba for game threads matching home/away teams on a given date range.
    """
    subreddit = reddit.subreddit("nba")
    local_timezone = timezone(local_tz)
    target_date_start_local = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=local_timezone)
    date_range_start_local = target_date_start_local - timedelta(days=1)
    date_range_end_local = target_date_start_local + timedelta(days=1, seconds=86399)

    date_range_start_utc = date_range_start_local.astimezone(utc)
    date_range_end_utc = date_range_end_local.astimezone(utc)

    game_threads = []
    search_query = f"{home_team} @ {away_team}"
    for submission in subreddit.search(search_query, sort="new"):
        created_utc = datetime.utcfromtimestamp(submission.created_utc).replace(tzinfo=utc)
        if date_range_start_utc <= created_utc <= date_range_end_utc:
            if is_game_thread(submission.title, home_team, away_team):
                game_threads.append({
                    "title": submission.title,
                    "url": submission.url,
                    "created_utc": created_utc,
                    "id": submission.id
                })

    return game_threads

def fetch_player_comments(thread, player_name):
    """
    Fetch all comments from the thread that mention the player_name
    or any of its known nicknames.
    """
    nicknames = PLAYER_NICKNAMES.get(player_name, [])
    keywords = [player_name] + nicknames

    thread.comments.replace_more(limit=0)
    comments = thread.comments.list()

    player_mentions = [comment.body for comment in comments if any(keyword.lower() in comment.body.lower() for keyword in keywords)]
    return player_mentions[:5]  # Limit the number of comments to 5

def convert_to_minutes(iso_duration):
    """
    Convert an ISO 8601 duration (e.g. 'PT34M12S') to integer minutes.
    """
    try:
        duration = isodate.parse_duration(iso_duration)
        return int(duration.total_seconds() // 60)
    except Exception as e:
        print(f"Error parsing duration {iso_duration}: {e}")
        return 0

@app.route("/")
def home():
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    if date_str == 'today':
        date_str = datetime.now().strftime('%Y-%m-%d')

    date = datetime.strptime(date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
    scoreboard2 = ScoreboardV2(game_date=date, league_id="00", day_offset=0)
    games_data = scoreboard2.get_normalized_dict()["GameHeader"]

    games_list = []
    for game in games_data:
        game_status = game.get('GAME_STATUS_TEXT', 'Unknown Status').strip()
        click = False
        if game_status in ['1st Qtr', '2nd Qtr', '3rd Qtr', '4th Qtr']:
            box_score = boxscore.BoxScore(game_id=game.get('GAME_ID')).get_dict()
            game_status = box_score['game']['gameStatusText']
            click = True

        games_list.append({
            "game_id": game.get('GAME_ID'),
            "home_team": TEAM_ID_TO_NAME.get(game.get('HOME_TEAM_ID'), "Unknown Home Team"),
            "away_team": TEAM_ID_TO_NAME.get(game.get('VISITOR_TEAM_ID'), "Unknown Away Team"),
            "status": game_status,
            "clickable": (
                'Final' in game_status or
                click or
                'Halftime' in game_status or
                'End of' in game_status
            ),
        })

    return render_template("games.html", games=games_list, date=date, datetime=datetime, timedelta=timedelta)

@app.route("/game/<game_id>")
def game_details(game_id):
    box_score_data = boxscore.BoxScore(game_id=game_id).get_dict()
    game_time_utc = box_score_data['game']['gameTimeUTC']
    utc_time = datetime.strptime(game_time_utc, '%Y-%m-%dT%H:%M:%SZ')
    local_timezone = timezone('US/Eastern')
    local_time = utc.localize(utc_time).astimezone(local_timezone)
    game_date = local_time.strftime('%Y-%m-%d')

    game_data = {
        "home_team": TEAM_ID_TO_NAME[box_score_data['game']['homeTeam']['teamId']],
        "away_team": TEAM_ID_TO_NAME[box_score_data['game']['awayTeam']['teamId']],
        "score": f"{box_score_data['game']['homeTeam']['score']} - {box_score_data['game']['awayTeam']['score']}",
        "status": box_score_data['game']['gameStatusText'],
    }

    home_team = game_data['home_team']
    away_team = game_data['away_team']
    game_threads = fetch_game_threads_by_team_and_date_range(home_team, away_team, game_date)
    selected_thread = reddit.submission(id=game_threads[0]['id']) if game_threads else None

    player_data = []
    for team_key in ['homeTeam', 'awayTeam']:
        team_info = box_score_data['game'][team_key]
        for player in team_info['players']:
            stats = player.get('statistics', {})
            player_name = player['name']

            if selected_thread:
                comments = fetch_player_comments(selected_thread, player_name)
                sentiment_scores = analyze_sentiment(comments)
                average_sentiment = (
                    sum(sentiment_scores) / len(sentiment_scores)
                    if sentiment_scores else None
                )
            else:
                average_sentiment = None
                comments = []

            fg_attempts = stats.get('fieldGoalsAttempted', 0)
            fg_made = stats.get('fieldGoalsMade', 0)
            ft_attempts = stats.get('freeThrowsAttempted', 0)
            ft_made = stats.get('freeThrowsMade', 0)

            fg_pct = (fg_made / fg_attempts * 100) if fg_attempts > 0 else 0
            ft_pct = (ft_made / ft_attempts * 100) if ft_attempts > 0 else 0

            fg_bonus = 0.1 * fg_pct * fg_attempts
            ft_bonus = 0.1 * ft_pct * ft_attempts

            performance_score = (
                (stats.get('points', 0) * 1.0) +
                (stats.get('assists', 0) * 1.5) +
                (stats.get('reboundsTotal', 0) * 1.2) +
                (stats.get('steals', 0) * 2.0) +
                (stats.get('blocks', 0) * 2.0) -
                (stats.get('turnovers', 0) * 2.0) -
                (0.7 * (fg_attempts - fg_made)) -
                (0.5 * (ft_attempts - ft_made)) +
                fg_bonus +
                ft_bonus
            ) / 10

            player_data.append({
                "team": team_info['teamName'],
                "name": player_name,
                "points": stats.get('points', 0),
                "rebounds": stats.get('reboundsTotal', 0),
                "assists": stats.get('assists', 0),
                "steals": stats.get('steals', 0),
                "blocks": stats.get('blocks', 0),
                "turnovers": stats.get('turnovers', 0),
                "fg_pct": round(fg_pct, 2),
                "ft_pct": round(ft_pct, 2),
                "performance_score": round(performance_score, 1),
                "average_sentiment": round(average_sentiment, 2) if average_sentiment is not None else "N/A",
                "top_comments": comments if comments else ["No comments found."],
            })

    ranked_players = sorted(player_data, key=lambda x: x['performance_score'], reverse=True)

    return render_template(
        "details.html",
        game=game_data,
        players=ranked_players,
        date=game_date
    )

if __name__ == "__main__":
    app.run(debug=True)

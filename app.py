from flask import Flask, render_template, request
from nba_api.live.nba.endpoints import scoreboard
from nba_api.stats.endpoints import ScoreboardV2
from nba_api.live.nba.endpoints import boxscore
from datetime import datetime, timedelta
from pytz import timezone, utc
import isodate
import praw
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import re


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
    client_id="hvEaR2ZB0YcgERqdWuZyBw",            # Replace with your Reddit app's client ID
    client_secret="CYKgXBCPR-zd9LmYEfFou6vGOEh8Kg",    # Replace with your Reddit app's secret
    user_agent="nba_tracker by /u/resker2"  # Replace with your Reddit username
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
    print("Analyzing sentiment...")
    analyzer = SentimentIntensityAnalyzer()
    sentiment_scores = []
    for comment in comments:
        sentiment = analyzer.polarity_scores(comment)['compound']
        sentiment_scores.append(sentiment)
    return sentiment_scores

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
    print(f"Fetching comments mentioning '{player_name}' or nicknames...")

    # Get nicknames for the player
    nicknames = PLAYER_NICKNAMES.get(player_name, [])
    # The keywords to look for in the comments
    keywords = [player_name] + nicknames

    thread.comments.replace_more(limit=0)  # Load all comments
    comments = thread.comments.list()

    player_mentions = []
    for comment in comments:
        if any(keyword.lower() in comment.body.lower() for keyword in keywords):
            player_mentions.append(comment.body)

    print(f"Found {len(player_mentions)} comments mentioning '{player_name}' or nicknames.")
    return player_mentions

TEAM_ID_TO_NAME = {
    1610612737: "Atlanta Hawks",
    1610612738: "Boston Celtics",
    1610612739: "Cleveland Cavaliers",
    1610612740: "New Orleans Pelicans",
    1610612741: "Chicago Bulls",
    1610612742: "Dallas Mavericks",
    1610612743: "Denver Nuggets",
    1610612744: "Golden State Warriors",
    1610612745: "Houston Rockets",
    1610612746: "Los Angeles Clippers",
    1610612747: "Los Angeles Lakers",
    1610612748: "Miami Heat",
    1610612749: "Milwaukee Bucks",
    1610612750: "Minnesota Timberwolves",
    1610612751: "Brooklyn Nets",
    1610612752: "New York Knicks",
    1610612753: "Orlando Magic",
    1610612754: "Indiana Pacers",
    1610612755: "Philadelphia 76ers",
    1610612756: "Phoenix Suns",
    1610612757: "Portland Trail Blazers",
    1610612758: "Sacramento Kings",
    1610612759: "San Antonio Spurs",
    1610612760: "Oklahoma City Thunder",
    1610612761: "Toronto Raptors",
    1610612762: "Utah Jazz",
    1610612763: "Memphis Grizzlies",
    1610612764: "Washington Wizards",
    1610612765: "Detroit Pistons",
    1610612766: "Charlotte Hornets"
}

PLAYER_NICKNAMES = {
    "LeBron James": ["King James", "LBJ", "Bron", "LeBron", "James"],
    "Stephen Curry": ["Steph", "Chef Curry", "Baby-Faced Assassin", "Curry"],
    "Anthony Davis": ["AD", "Davis", "The Brow"],
    "Jalen Green": ["JG", "Green Machine", "JGreen"],
    "Victor Wembanyama": ["Wemby", "Wembanyama"],
    "LaMelo Ball": ["Melo", "LaMelo"],
    "Jarrett Allen": ["Jarrett", "Allen"],
    "Darius Garland": ["DG", "Garland", "Darius"],
    "Evan Mobley": ["Mobley", "Evan"],
    "Cade Cunningham": ["Cade"],
    "Dillon Brooks": ["Dillon", "Brooks"],
    "Bobby Portis": ["Bobby", "Portis"],
    "Tari Eason": ["Tari", "Eason"],
    "Amen Thompson": ["Amen", "Thompson"],
    "Giannis Antetokounmpo": ["Giannis", "Antetokounmpo", "Greek Freak"],
    "Damian Lillard": ["Dame", "Lillard", "Dame Time"],
    "Fred VanVleet": ["FVV", "VanVleet", "Fred"],
    "De'Aaron Fox": ["Fox"],

    # Added more notable players
    "Kevin Durant": ["KD", "Durant", "Slim Reaper", "Easy Money Sniper"],
    "Kyrie Irving": ["Kyrie", "Irving", "Uncle Drew"],
    "James Harden": ["Harden", "Beard", "The Beard"],
    "Nikola Jokic": ["Jokic", "Joker", "Nikola"],
    "Joel Embiid": ["Embiid", "Joel", "The Process"],
    "Luka Doncic": ["Luka", "Doncic", "Luka Magic", "Dončić"]
}

def convert_to_minutes(iso_duration):
    """
    Convert an ISO 8601 duration (e.g. 'PT34M12S') to integer minutes.
    """
    try:
        duration = isodate.parse_duration(iso_duration)
        total_minutes = int(duration.total_seconds() // 60)
        return total_minutes
    except Exception as e:
        print(f"Error parsing duration {iso_duration}: {e}")
        return 0  # Default to 0 if parsing fails

@app.route("/")
def home():
    # Get the date from the query parameter, default to today's date
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

    # Check if the date is 'today' and convert it to today's date
    if date_str == 'today':
        date_str = datetime.now().strftime('%Y-%m-%d')

    # Parse the date to ensure it's in the correct format
    date = datetime.strptime(date_str, '%Y-%m-%d').strftime('%Y-%m-%d')

    scoreboard2 = ScoreboardV2(game_date=date, league_id="00", day_offset=0)
    games_data = scoreboard2.get_normalized_dict()["GameHeader"]

    games_list = []
    for game in games_data:
        game_status = game.get('GAME_STATUS_TEXT', 'Unknown Status').strip()
        click = False

        # If the game is in progress, fetch the box score to get an updated gameStatusText
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
    # Fetch game box score
    box_score_data = boxscore.BoxScore(game_id=game_id).get_dict()

    # Extract game time in UTC
    game_time_utc = box_score_data['game']['gameTimeUTC']

    # Convert UTC time to local timezone (e.g., Eastern Time)
    utc_time = datetime.strptime(game_time_utc, '%Y-%m-%dT%H:%M:%SZ')
    local_timezone = timezone('US/Eastern')
    local_time = utc.localize(utc_time).astimezone(local_timezone)

    # Extract the game's local date
    game_date = local_time.strftime('%Y-%m-%d')

    # Extract game details
    game_data = {
        "home_team": TEAM_ID_TO_NAME[box_score_data['game']['homeTeam']['teamId']],
        "away_team": TEAM_ID_TO_NAME[box_score_data['game']['awayTeam']['teamId']],
        "score": f"{box_score_data['game']['homeTeam']['score']} - {box_score_data['game']['awayTeam']['score']}",
        "status": box_score_data['game']['gameStatusText'],
    }

    home_team = game_data['home_team']
    away_team = game_data['away_team']

    # Fetch game threads
    game_threads = fetch_game_threads_by_team_and_date_range(home_team, away_team, game_date)
    selected_thread = reddit.submission(id=game_threads[0]['id']) if game_threads else None

    # Extract player statistics and sentiment
    player_data = []
    for team_key in ['homeTeam', 'awayTeam']:
        team_info = box_score_data['game'][team_key]
        for player in team_info['players']:
            stats = player.get('statistics', {})
            player_name = player['name']

            # Fetch comments & sentiment
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

            # Basic stats
            points = stats.get('points', 0)
            assists = stats.get('assists', 0)
            rebounds = stats.get('reboundsTotal', 0)
            steals = stats.get('steals', 0)
            blocks = stats.get('blocks', 0)
            turnovers = stats.get('turnovers', 0)
            fg_attempts = stats.get('fieldGoalsAttempted', 0)
            fg_made = stats.get('fieldGoalsMade', 0)
            ft_attempts = stats.get('freeThrowsAttempted', 0)
            ft_made = stats.get('freeThrowsMade', 0)
            minutes = convert_to_minutes(stats.get('minutes'))

            # Calculate performance score
            fg_missed = fg_attempts - fg_made
            ft_missed = ft_attempts - ft_made
            fg_pct = (fg_made / fg_attempts * 100) if fg_attempts > 0 else 0
            ft_pct = (ft_made / ft_attempts * 100) if ft_attempts > 0 else 0

            fg_bonus = 0.1 * fg_pct * fg_attempts
            ft_bonus = 0.1 * ft_pct * ft_attempts

            performance_score = (
                (points * 1.0) +
                (assists * 1.5) +
                (rebounds * 1.2) +
                (steals * 2.0) +
                (blocks * 2.0) -
                (turnovers * 2.0) -
                (0.7 * fg_missed) -
                (0.5 * ft_missed) +
                fg_bonus +
                ft_bonus
            ) / 10

            player_data.append({
                "team": team_info['teamName'],
                "name": player_name,
                "points": points,
                "rebounds": rebounds,
                "assists": assists,
                "steals": steals,
                "blocks": blocks,
                "turnovers": turnovers,
                "fg_made": fg_made,
                "fg_attempts": fg_attempts,
                "ft_made": ft_made,
                "ft_attempts": ft_attempts,
                "fg_pct": round(fg_pct, 2),
                "ft_pct": round(ft_pct, 2),
                "performance_score": round(performance_score, 1),
                "minutes": minutes,
                "average_sentiment": round(average_sentiment, 2) if average_sentiment is not None else "N/A",
                "top_comments": comments if comments else ["No comments found."],
            })

    # Sort players by performance score (descending)
    ranked_players = sorted(player_data, key=lambda x: x['performance_score'], reverse=True)

    return render_template(
        "details.html",
        game=game_data,
        players=ranked_players,
        date=game_date
    )

if __name__ == "__main__":
    app.run(debug=True)

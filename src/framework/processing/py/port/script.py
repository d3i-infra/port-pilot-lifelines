import itertools
import port.api.props as props
from port.api.commands import CommandSystemDonate, CommandUIRender

import pandas as pd
import zipfile
import json
import datetime
from collections import defaultdict, namedtuple
from contextlib import suppress

##########################
# TikTok file processing #
##########################

filter_start = datetime.datetime(2021, 1, 1)
filter_end = datetime.datetime(2025, 1, 1)

datetime_format = "%Y-%m-%d %H:%M:%S"


def get_in(data_dict, *key_path):
    for k in key_path:
        data_dict = data_dict.get(k, None)
        if data_dict is None:
            return None
    return data_dict


def get_activity_video_browsing_list_data(data):
    return get_in(data, "Activity", "Video Browsing History", "VideoList")


def get_comment_list_data(data):
    return get_in(data, "Comment", "Comments", "CommentsList")


def get_date_filtered_items(items):
    for item in items:
        timestamp = datetime.datetime.strptime(item["Date"], datetime_format)
        if timestamp < filter_start or timestamp > filter_end:
            continue
        yield (timestamp, item)


def get_count_by_date_key(timestamps, key_func):
    """Returns a dict of the form (key, count)

    The key is determined by the key_func, which takes a datetime object and
    returns an object suitable for sorting and usage as a dictionary key.

    The returned list is sorted by key.
    """
    item_count = defaultdict(int)
    for timestamp in timestamps:
        item_count[key_func(timestamp)] += 1
    return sorted(item_count.items())


def get_all_first(items):
    return (i[0] for i in items)


def hourly_key(date):
    return date.replace(minute=0, second=0, microsecond=0)


def daily_key(date):
    return date.date()


def get_sessions(timestamps):
    """Returns a list of tuples of the form (start, end, duration)

    The start and end are datetime objects, and the duration is a timedelta
    object.
    """
    timestamps = list(sorted(timestamps))
    if len(timestamps) == 0:
        return []
    if len(timestamps) == 1:
        return [(timestamps[0], timestamps[0], datetime.timedelta(0))]

    sessions = []
    start = timestamps[0]
    end = timestamps[0]
    for prev, cur in zip(timestamps, timestamps[1:]):
        if cur - prev > datetime.timedelta(hours=1):
            sessions.append((start, end, end - start))
            start = cur
        end = cur
    sessions.append((start, end, end - start))
    return sessions


def get_json_data(zip_file):
    with zipfile.ZipFile(zip_file, "r") as zip:
        for name in zip.namelist():
            if not name.endswith(".json"):
                continue
            with zip.open(name) as json_file:
                yield json.load(json_file)


def extract_summary_data(data):
    summary_data = {
        "Description": [
            "Followers",
            "Following",
            "Likes received",
            "Videos posted",
            "Likes given",
            "Comments posted",
        ],
        "Number": [
            len(get_in(data, "Activity", "Follower List", "FansList")),
            len(get_in(data, "Activity", "Following List", "Following")),
            get_in(
                data, "Profile", "Profile Information", "ProfileMap", "likesReceived"
            ),
            len(get_in(data, "Video", "Videos", "VideoList")),
            len(get_in(data, "Activity", "Like List", "ItemFavoriteList")),
            len(get_in(data, "Comment", "Comments", "CommentsList")),
        ],
    }

    return ExtractionResult(
        "tiktok_summary",
        props.Translatable(
            {"en": "Summary information", "nl": "Samenvatting gegevens"}
        ),
        pd.DataFrame(summary_data),
    )


def extract_passive_behavior(data):
    videos = get_all_first(
        get_date_filtered_items(get_activity_video_browsing_list_data(data))
    )
    video_counts = get_count_by_date_key(videos, hourly_key)

    df = pd.DataFrame(video_counts, columns=["Date", "Viewed Videos"])
    df["Hour"] = df["Date"].dt.hour
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    df = df.reindex(columns=["Date", "Hour", "Viewed Videos"])
    # df = df.set_index(['Date', 'Hour'])
    return ExtractionResult(
        "tiktok_passive",
        props.Translatable({"en": "Passive behaviour", "nl": "Passief gedrag"}),
        df,
    )


def extract_video_posts(data):
    videos = get_date_filtered_items(get_in(data, "Video", "Videos", "VideoList"))
    post_stats = defaultdict(lambda: defaultdict(int))
    for date, video in videos:
        hourly_stats = post_stats[date.replace(minute=0, second=0, microsecond=0)]
        hourly_stats["Videos posted"] += 1
        hourly_stats["Likes"] += int(video["Likes"])
    df = pd.DataFrame(post_stats).transpose()
    df["Date"] = df.index.strftime("%Y-%m-%d")
    df["Hour"] = df.index.hour
    df = df.reset_index(drop=True)
    df = df.reindex(columns=["Date", "Hour", "Videos posted", "Likes"])
    return ExtractionResult(
        "tiktok_posts",
        props.Translatable({"en": "Video posts", "nl": "Video posts"}),
        df,
    )


def extract_active_behavior(data):
    comments = get_all_first(
        get_date_filtered_items(get_in(data, "Comment", "Comments", "CommentsList"))
    )
    comment_counts = get_count_by_date_key(comments, hourly_key)

    df = pd.DataFrame(comment_counts, columns=["Date", "Comment count"])
    df["Hour"] = df["Date"].dt.hour
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    df = df.reindex(columns=["Date", "Hour", "Comment count"])
    # df = df.set_index(['Date', 'Hour'])
    return ExtractionResult(
        "tiktok_active",
        props.Translatable({"en": "Active behaviour", "nl": "Actief gedrag"}),
        df,
    )


def extract_session_data(data):
    session_paths = [
        ("Video", "Videos", "VideoList"),
        ("Activity", "Video Browsing History", "VideoList"),
        ("Comment", "Comments", "CommentsList"),
    ]

    item_lists = [get_in(data, *path) for path in session_paths]
    dates = get_all_first(get_date_filtered_items(itertools.chain(*item_lists)))

    sessions = get_sessions(dates)
    df = pd.DataFrame(sessions, columns=["Start", "End", "Duration"])
    df["Start"] = df["Start"].dt.strftime("%Y-%m-%d %H:%M")
    df["Duration (in minutes)"] = (df["Duration"].dt.total_seconds() / 60).round(2)
    df = df.drop("End", axis=1)
    df = df.drop("Duration", axis=1)

    return ExtractionResult(
        "tiktok_sessions",
        props.Translatable({"en": "Session information", "nl": "Sessie informatie"}),
        df,
    )


def extract_tiktok_data(zip_file):
    for data in get_json_data(zip_file):
        return [
            extract_summary_data(data),
            extract_video_posts(data),
            extract_active_behavior(data),
            extract_passive_behavior(data),
            extract_session_data(data),
        ]

        # return df

        # videos = list(get_all_first(get_date_filtered_items(get_video_list_data(data))))
        # video_counts = get_count_by_date_key(videos, hourly_key)
        # table_title = props.Translatable(
        #     {"en": "TikTok video browsing history", "nl": "TikTok video geschiedenis"}
        # )
        # print(video_counts)
        # data_frame = pd.DataFrame(video_counts, columns=["Hour", "View Count"])
        # return [
        #     props.PropsUIPromptConsentFormTable(
        #         "tiktok_video_counts", table_title, data_frame
        #     )
        # ]

        # comment_list_dates = list(get_all_first(get_date_filtered_items(get_comment_list_data(data))))
        # yield sessions


# data = json.load(open(sys.argv[1]))

# from pprint import pprint
# video_dates = list(get_all_first(get_date_filtered_items(get_video_list_data(data))))
# pprint(get_count_by_date_key(video_dates, hourly_key))
# pprint(get_count_by_date_key(video_dates, daily_key))
# print("#"*80)
# comment_list_dates = list(get_all_first(get_date_filtered_items(get_comment_list_data(data))))
# pprint(get_count_by_date_key(comment_list_dates, hourly_key))
# pprint(get_count_by_date_key(comment_list_dates, daily_key))

# sessions = get_sessions(itertools.chain(video_dates, comment_list_dates))
# pprint(sessions)


######################
# Data donation flow #
######################


ExtractionResult = namedtuple("ExtractionResult", ["id", "title", "data_frame"])


class SkipToNextStep(Exception):
    pass


class DataDonationProcessor:
    def __init__(self, platform, mime_types, extractor, session_id):
        self.platform = platform
        self.mime_types = mime_types
        self.extractor = extractor
        self.session_id = session_id
        self.progress = 0
        self.meta_data = []

    def process(self):
        with suppress(SkipToNextStep):
            while True:
                file_result = yield from self.prompt_file()

                self.log(f"extracting file")
                try:
                    extraction_result = self.extract_data(file_result.value)
                except IOError as e:
                    self.log(f"prompt confirmation to retry file selection")
                    # retry_result = yield render_donation_page(
                    #     self.platform, retry_confirmation(self.platform), self.progress
                    # )
                    # if retry_result.__type__ == "PayloadTrue":
                    #     self.log(f"skip due to invalid file")
                    #     continue

                    # self.log(f"retry prompt file")
                    # return
                else:
                    self.log(f"extraction successful, go to consent form")
                    yield from self.prompt_consent(extraction_result)

    def prompt_file(self):
        description = props.Translatable(
            {
                "en": f"Please follow the download instructions and choose the file that you stored on your device. Click “Skip” at the right bottom, if you do not have a {self.platform} file. ",
                "nl": f"Volg de download instructies en kies het bestand dat u opgeslagen heeft op uw apparaat. Als u geen {self.platform} bestand heeft klik dan op “Overslaan” rechts onder.",
            }
        )
        prompt_file = props.PropsUIPromptFileInput(description, self.mime_types)
        file_result = yield render_donation_page(
            self.platform, prompt_file, self.progress
        )
        if file_result.__type__ != "PayloadString":
            self.log(f"skip to next step")
            raise SkipToNextStep()
        return file_result

    def log(self, message):
        self.meta_data.append(("debug", f"{self.platform}: {message}"))

    def extract_data(self, file):
        return self.extractor(file)

    def prompt_consent(self, data):
        log_title = props.Translatable({"en": "Log messages", "nl": "Log berichten"})

        tables = [
            props.PropsUIPromptConsentFormTable(table.id, table.title, table.data_frame)
            for table in data
        ]
        meta_frame = pd.DataFrame(self.meta_data, columns=["type", "message"])
        meta_table = props.PropsUIPromptConsentFormTable(
            "log_messages", log_title, meta_frame
        )
        self.log(f"prompt consent")
        consent_result = yield render_donation_page(
            self.platform,
            props.PropsUIPromptConsentForm(tables, [meta_table]),
            self.progress,
        )

        if consent_result.__type__ == "PayloadJSON":
            self.log(f"donate consent data")
            yield donate(f"{self.sessionId}-{self.platform}", consent_result.value)


class DataDonation:
    def __init__(self, platform, mime_types, extractor):
        self.platform = platform
        self.mime_types = mime_types
        self.extractor = extractor

    def __call__(self, session_id):
        processor = DataDonationProcessor(
            self.platform, self.mime_types, self.extractor, session_id
        )
        yield from processor.process()


tik_tok_data_donation = DataDonation(
    "TikTok", "application/zip, text/plain", extract_tiktok_data
)


def process(session_id):
    progress = 0
    yield donate(f"{session_id}-tracking", '[{ "message": "user entered script" }]')
    yield from tik_tok_data_donation(session_id)
    yield render_end_page()


def render_end_page():
    page = props.PropsUIPageEnd()
    return CommandUIRender(page)


def render_donation_page(platform, body, progress):
    header = props.PropsUIHeader(props.Translatable({"en": platform, "nl": platform}))

    footer = props.PropsUIFooter(progress)
    page = props.PropsUIPageDonation(platform, header, body, footer)
    return CommandUIRender(page)


def retry_confirmation(platform):
    text = props.Translatable(
        {
            "en": f"Unfortunately, we cannot process your {platform} file. Continue, if you are sure that you selected the right file. Try again to select a different file.",
            "nl": f"Helaas, kunnen we uw {platform} bestand niet verwerken. Weet u zeker dat u het juiste bestand heeft gekozen? Ga dan verder. Probeer opnieuw als u een ander bestand wilt kiezen.",
        }
    )
    ok = props.Translatable({"en": "Try again", "nl": "Probeer opnieuw"})
    cancel = props.Translatable({"en": "Continue", "nl": "Verder"})
    return props.PropsUIPromptConfirm(text, ok, cancel)


def prompt_consent(id, data, meta_data):
    table_title = props.Translatable(
        {"en": "Zip file contents", "nl": "Inhoud zip bestand"}
    )

    log_title = props.Translatable({"en": "Log messages", "nl": "Log berichten"})

    data_frame = pd.DataFrame(data, columns=["filename", "compressed size", "size"])
    table = props.PropsUIPromptConsentFormTable("zip_content", table_title, data_frame)
    meta_frame = pd.DataFrame(meta_data, columns=["type", "message"])
    meta_table = props.PropsUIPromptConsentFormTable(
        "log_messages", log_title, meta_frame
    )
    return props.PropsUIPromptConsentForm([table], [meta_table])


def donate(key, json_string):
    return CommandSystemDonate(key, json_string)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        print(extract_tiktok_data(sys.argv[1]))
    else:
        print("please provide a zip file as argument")

import json
import re
import time
import base64
import requests
from bs4 import BeautifulSoup as bs
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from audiobooker.scrappers.librivox import Librivox


def search(query, search_type="title", page=0):
    search_request = SearchRequest(query, search_type, page)
    return search_request.aggregate_request_data()


def strip_i_tag_from_soup(soup):
    subheadings = soup.find_all("i")
    for subheading in subheadings:
        subheading.decompose()


class SearchRequest:
    col_names = ["ID", "Author", "Title", "Publisher", "Year", "Pages", "Language", "Size", "Extension",
                 "Mirror_1", "Mirror_2", "Mirror_3", "Mirror_4", "Mirror_5", "Edit"]

    def __init__(self, query, search_type="title", page=0):
        self.query = query
        self.search_type = search_type
        self.page = page

    def get_search_page(self):
        query_parsed = "%20".join(self.query.split(" "))
        page = self.page
        search_url = "http://gen.lib.rus.ec/search.php?req={}&column={}&page={}".format(
            query_parsed, self.search_type.lower(), page)
        search_page = requests.get(search_url)
        return search_page

    def aggregate_request_data(self):
        search_page = self.get_search_page()
        soup = bs(search_page.text, 'lxml')
        strip_i_tag_from_soup(soup)
        information_table = soup.find_all('table')[2]
        count = soup.find_all('font')[2].string.split('|')[0].split(' ')[0]
        raw_data = [
            [
                td.a['href'] if td.find('a') and td.find('a').has_attr("title") and td.find('a')["title"] != ""
                else ''.join(td.stripped_strings)
                for td in row.find_all("td")
            ]
            # Skip row 0 as it is the headings row
            for row in information_table.find_all("tr")[1:]
        ]
        cols = ["id", "title", "author",
                "publisher", "year", "size", "download"]
        output_data = [dict(zip(cols, self.sanitize(row))) for row in raw_data]
        return json.dumps(output_data), count

    @staticmethod
    def sanitize(row):
        indices = 5, 6, 8
        row = [i for j, i in enumerate(row[:10]) if j not in indices]
        row = [p.replace("'", "\'").replace('"', '\"') for p in row]
        size = row[-2].split(' ')
        val = size[0]
        ext = size[1]
        if ext == "Kb":
            val = float(val) / 1024
            ext = "Mb"
        size = "{:.2f} {}".format(round(float(val), 2), ext).replace(".00", "")
        row[-2] = size
        row[1], row[2] = row[2], row[1]
        return row


app = FastAPI()

origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Hello, World!"}


@app.get("/query/{option}/{query}/{page}")
async def read_item(option, query, page):
    start = time.time()
    query = query.lower()
    result = search(query, option, page)
    end = time.time()
    time_elapsed = str(end - start)
    if result == "[]":
        count = '0'
    else:
        count = str(result[1])
    data = '{"time": ' + time_elapsed + ', "results": ' + \
           result[0] + ', "count": "' + count + '"}'
    return Response(content=data, media_type="application/json")


# noinspection PyBroadException
@app.get("/book/{code}")
async def book_info(code):
    base_url = "http://library.lol"
    link = base_url + "/main/" + code
    markup = requests.get(link).text
    soup = bs(markup, "lxml")
    image = base_url + soup.find("img")['src']
    response = requests.get(image).content
    encoded_image_data = "data:image/png;base64," + \
                         base64.b64encode(response).decode('utf-8')
    direct_url = soup.select_one("a[href*=cloudflare]")["href"]
    heading = soup.find("h1").text.split(":")
    title = heading[0]
    subtitle = " "
    if len(heading) > 1:
        subtitle = heading[1].strip()
    try:
        author_prefix = "Author"
        author = str(soup.select_one('p:contains({})'.format(
            author_prefix)))[14:]
        author = re.sub('<[^<]+?>', '', author)
    except:
        author = " "
    try:
        year = re.sub('<[^<]+?>', '', str(soup.select_one('p:contains(Publisher)')).split(",")[
            1].removeprefix(" Year: "))
    except IndexError:
        year = " "
    try:
        description_prefix = "Description"
        description = str(soup.select_one('div:contains({})'.format(
            description_prefix))).removeprefix("<div>" + description_prefix + ":<br/>").removesuffix("</div>")
        description = description.replace("<br />", "")
        description = re.sub('<[^<]+?>', '', description)
        description = ' '.join(description.split())
        description = description.replace("'", "\'").replace('"', '')
        description = description.replace('\n', '')
    except:
        description = " "
    data = '{"title": "' + title + '", "subtitle": "' + subtitle + \
           '", "description": "' + description + '", "year": "' + \
           year + '", "author": "' + author + '", "image": "' + \
           encoded_image_data + '", "direct_url": "' + direct_url + '"}'
    return Response(content=data, media_type="application/json")


@app.get("/vox/{query}")
async def read_item(query):
    book = Librivox.search_audiobooks(title=query)[0]
    data = '{"title": "' + str(book.title) + '", "description": "' + str(book.description) + '", "authors": "' + str(
        book.authors) + '", "url": "' + str(book.url) + '", "streams": ' + str(book.streams).replace("'", '"') + '}'
    return Response(content=data, media_type="application/json")

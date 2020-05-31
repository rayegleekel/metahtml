'''
Timestamps are notoriously difficult to work with because they are deceptively complicated.
To better understand the issues of working with timestamps, see:

1. https://infiniteundo.com/post/25326999628/falsehoods-programmers-believe-about-time
1. http://www.creativedeletion.com/2015/01/28/falsehoods-programmers-date-time-zones.html
1. timezones: https://www.youtube.com/watch?v=-5wpm-gesOY
1. internationalization: https://www.youtube.com/watch?v=0j74jcxSunY
1. UNIX time: https://www.youtube.com/watch?v=QJQ691PTKsA

Timestamps that an article was published on are even more difficult to work with,
because there are several domain specific problems:

1. The timestamps can be specified in a local dialect of a language,
   so existing timestamp parsing code may not work.

1. The "accuracy" of a timestamp depends on the publication venue.
   Some magazines only specify the year/month that an article was published in;
   some specify the exact day;
   and some specify the exact second.

1. Many venues do not specify the timezone of the timestamp,
   and so this must be inferred from the venue location.
   But venue locations can change timezones.

1. Articles are sometimes published in multiple locations (e.g. online and in print) at different times;
   which one of these times should be the canonical time?
   Some articles have multiple timestamps listed even for the same location depending on which metadata source you use.
   See for example:
   https://www.breitbart.com/national-security/2019/11/02/north-korea-claims-test-of-super-large-multiple-rocket-launchers/

1. Articles published online often change over time.
   Should the publication date be the date of the original publication or the date of the change?
   Sometimes the changes are clearly documented in the webpage,
   but typically they are not.
   See for example: 
   * https://dailycaller.com/2020/04/13/new-york-times-dean-baquet-joe-biden-tara-reade-sexual-assault-article-edit/
   * http://newsdiffs.org/
   Some websites like time.gov/reddit.com are continuously changing and will be totally different everytime they get loaded.

1. A webpage may contain multiple "articles" inside, each written at different times.
   For example, forum posts and archive pages.

1. The time listed may not reflect the true time that the article was actually written.
   This could be because the server's clock is wrong (non-malicious, probably only by a few minutes),
   or because an editor has maliciously changed the time of posting.
'''

import copy
import datetime
import lxml
import lxml.html
import re
from urllib.parse import urlparse

# non-standard timestamp parsing libraries
import dateparser
import dateutil
import dateutil.tz
from dateutil.parser import parse as date_parser

# For timestamps without timezones, we apply these timezones.
# This gives us a worst case estimate for what the actual time represented is.
# The UTC-offsets are represented in seconds.
worst_tz_lo = dateutil.tz.tzoffset('worst_lo',12*60*60)
worst_tz_hi = dateutil.tz.tzoffset('worst_hi',-12*60*60)


def parse_timestamp_str(timestamp_str, parser=None):
    '''
    Given a string representing a timestamp

    python date libraries:
    1. dateparser: https://blog.scrapinghub.com/2015/11/09/parse-natural-language-dates-with-dateparser
    1. natty: https://github.com/eadmundo/python-natty
    '''

    # don't waste our time parsing if no timestamp_str was passed in
    if timestamp_str is None or len(timestamp_str)==0:
        return None

    # if no parser specified, then try them all
    if parser is None:
        result = parse_timestamp_str(timestamp_str, parser='dateutil')
        if result['timestamp_lo'] is None:
            result = parse_timestamp_str(timestamp_str, parser='dateparser')
        return result

    # parse the date
    if parser=='dateutil':
        default_lo = datetime.datetime(
            year            = 1,
            month           = 1,
            day             = 1,
            hour            = 0,
            minute          = 0,
            second          = 0,
            microsecond     = 0,
            tzinfo          = None
            )
        default_hi = datetime.datetime(
            year            = 9999, 
            month           = 12,
            day             = 31,
            hour            = 23,
            minute          = 59,
            second          = 59,
            microsecond     = 999999,
            tzinfo          = None
            )
        try:
            from dateutil.parser import parse as date_parser
            tzinfos = {
                'IST' : 5.5*60*60,
                'CEST' : 2*60*60,
                'CET' : 1*60*60,
                'BST' : 1*60*60,
                'ET' : -5*60*60,
                'EST' : -5*60*60,
                'EDT' : -4*60*60,
                }
            timestamp_lo = date_parser(timestamp_str, fuzzy=True, tzinfos=tzinfos, default=default_lo)
            timestamp_hi = date_parser(timestamp_str, fuzzy=True, tzinfos=tzinfos, default=default_hi)

            # check for common parsing errors that are caused by foreign dates
            # for example, if date_parser finds an hour but not a day,
            # then this is almost certainly an error
            if ((timestamp_lo.year != timestamp_hi.year) or
                (timestamp_lo.month != timestamp_hi.month and timestamp_lo.day == timestamp_hi.day) or
                (timestamp_lo.day != timestamp_hi.day and timestamp_lo.hour == timestamp_hi.hour) or
                (timestamp_lo.hour != timestamp_hi.hour and timestamp_lo.minute == timestamp_hi.minute) or
                (timestamp_lo.minute != timestamp_hi.minute and timestamp_lo.second == timestamp_hi.second) or
                (timestamp_lo.second != timestamp_hi.second and timestamp_lo.microsecond == timestamp_hi.microsecond)
               ):
                timestamp_lo = None
                timestamp_hi = None

        except (ValueError, OverflowError, AttributeError, TypeError):
            # near all parse failures are due to URL dates without a day
            # specifier, e.g. /2014/04/
            timestamp_lo = None
            timestamp_hi = None

    elif parser=='dateparser':
        date_order = 'YMD'

        def remove_prefix(s, prefix):
            return s[len(prefix):] if s.startswith(prefix) else s

        # cs
        timestamp_str = re.sub('Zveřejněno dne ', '', timestamp_str)
        timestamp_str = re.sub(' v ', ' ', timestamp_str)
        # de
        timestamp_str = re.sub('Veröffentlicht auf ', '', timestamp_str)
        timestamp_str = re.sub(' um ', ' ', timestamp_str)
        # es 
        timestamp_str = re.sub('Publicado en ', '', timestamp_str)
        timestamp_str = re.sub(' a las ', ' ', timestamp_str)
        # it 
        timestamp_str = re.sub('Pubblicato su', '', timestamp_str)
        timestamp_str = re.sub(' alle ', ' ', timestamp_str)
        # fr
        timestamp_str = re.sub('Publié', '', timestamp_str)
        timestamp_str = re.sub(' à ', ' ', timestamp_str)
        # nl
        timestamp_str = re.sub('Gepubliceerd op', '', timestamp_str)
        timestamp_str = re.sub(' om ', ' ', timestamp_str)
        # pl
        timestamp_str = re.sub('Opublikowano w dniu ', '', timestamp_str)
        timestamp_str = re.sub(' o ', ' ', timestamp_str)
        # pt
        timestamp_str = re.sub('Publicado em', '', timestamp_str)
        timestamp_str = re.sub(' às ', ' ', timestamp_str)
        # ro
        timestamp_str = re.sub('Publicat pe ', '', timestamp_str)
        timestamp_str = re.sub(' la ', ' ', timestamp_str)

        timestamp_str = timestamp_str.strip()
        #print("timestamp_str=",timestamp_str)

        # see https://dateparser.readthedocs.io/en/latest/#dateparser.parse
        # for details on how to parse dates
        timestamp_lo = dateparser.parse(
            timestamp_str,
            settings = {
                'PARSERS' : ['timestamp','base-formats','absolute-time'],
                'DATE_ORDER' : date_order,
                'PREFER_DAY_OF_MONTH' : 'first',
                }
            )

        # NOTE: 
        # To get the upper range, 
        # we assume that if all time components equal 0,
        # then the time was not set.
        # This is not guaranteed to be the case, however.
        # If the timestamp_str is exactly midnight,
        # then this code will be excessively conservative in its range estimation,
        # placing the range anywhere in the following day.
        timestamp_hi = dateparser.parse(
            timestamp_str,
            settings = {
                'PARSERS' : ['timestamp','base-formats','absolute-time'],
                'DATE_ORDER' : date_order,
                'PREFER_DAY_OF_MONTH' : 'last',
                }
            )

        if timestamp_hi and timestamp_hi.microsecond==0 and timestamp_hi.second==0 and timestamp_hi.minute==0 and timestamp_hi.hour==0:
            timestamp_hi = datetime.datetime(
                year            = timestamp_hi.year,
                month           = timestamp_hi.month,
                day             = timestamp_hi.day,
                hour            = 23,
                minute          = 59,
                second          = 59,
                microsecond     = 999999,
                tzinfo          = timestamp_hi.tzinfo
                )

    # return dictionary
    return {
        'timestamp_lo' : timestamp_lo,
        'timestamp_hi' : timestamp_hi,
        'raw' : timestamp_str,
        'parser' : parser,
        }


def timestamp2str(timestamp):
    '''
    Converts a timestamp into a string with the appropriate accuracy.
    '''
    if timestamp is None:
        return
    timestamp_format = ''
    lo = timestamp['timestamp_lo']
    hi = timestamp['timestamp_hi']
    if lo.year == hi.year:
        timestamp_format += '%Y'
    if lo.month == hi.month:
        timestamp_format += '-%m'
    if lo.day == hi.day:
        timestamp_format += '-%d'
    if lo.hour == hi.hour:
        timestamp_format += ' %H'
    if lo.minute == hi.minute:
        timestamp_format += ':%M'
    if lo.second == hi.second:
        timestamp_format += ':%S'
    if lo.microsecond == hi.microsecond:
        timestamp_format += '.%f'
    timestamp_format += ' %Z'
    #print("lo=",lo)
    return str(lo) #lo.strftime(timestamp_format).strip()


def get_best_timestamps(timestamps, require_valid_for_hostname=True):
    '''
    Takes as timestamp a list of timestamp dictionaries,
    and removes redundant timestamps from the list.
    '''
    bests = []

    for timestamp in timestamps:
        found_match = False

        # skip timestamps that don't represent a time
        if timestamp is None or timestamp['timestamp_hi'] is None or timestamp['timestamp_lo'] is None:
            continue

        # skip timestamps not valid for the hostname
        if require_valid_for_hostname and not timestamp.get('is_valid_for_hostname'):
            continue

        # modified timestamps include worst case timezones if no timezone specified
        timestamp_lo_mod = timestamp['timestamp_lo']
        if timestamp_lo_mod.tzinfo is None:
            timestamp_lo_mod = copy.copy(timestamp_lo_mod).replace(tzinfo = worst_tz_lo)
        timestamp_hi_mod = timestamp['timestamp_hi']
        if timestamp_hi_mod.tzinfo is None:
            timestamp_hi_mod = copy.copy(timestamp_hi_mod).replace(tzinfo = worst_tz_hi)
        
        # loop through the currently found timestamps to check for duplicates
        for i,best in enumerate(bests):
            
            # modified timestamps include worst case timezones if no timezone specified
            best_lo_mod = best['timestamp_lo']
            if best_lo_mod.tzinfo is None:
                best_lo_mod = copy.copy(best_lo_mod).replace(tzinfo = worst_tz_lo)
            best_hi_mod = best['timestamp_hi']
            if best_hi_mod.tzinfo is None:
                best_hi_mod = copy.copy(best_hi_mod).replace(tzinfo = worst_tz_hi)

            # the input timestamp matches the best timestamp, but is more accurate;
            # therefore we replace the best timestamp with the timestamp
            if timestamp_lo_mod >= best_lo_mod and timestamp_hi_mod <= best_hi_mod:
                bests[i] = timestamp
                found_match = True

            # the input timestamp matches the best timestamp, but is less accurate;
            # therefore we do nothing
            elif timestamp_lo_mod <= best_lo_mod and timestamp_hi_mod >= best_hi_mod:
                found_match = True

            # else, the timestamp timestamp represents an entirely new date,
            # and so it should be added to the bests list

        if not found_match:
            bests.append(timestamp)

    # sort and return
    #bests.sort(key=lambda x: x['timestamp_lo'])

    return bests


def get_timestamp_published(html, url, **kwargs):
    '''
    Returns a timestamp dictionary that the input webpage was created on.

    See get_timestamp for details about the timestamp dictionary.
    '''

    xpaths = [

        # universal xpaths
        ( None, '//meta[@property="rnews:datePublished"]/@content' ),
        ( None, '//meta[@property="article:published_time"]/@content' ),
        ( None, '//meta[@property="og:published_time"]/@content' ),
        ( None, '//meta[@itemprop="datePublished"]/@datetime' ),
        ( None, '//meta[@pubdate="pubdate"]/@datetime' ),
        ( None, '//meta[@name="OriginalPublicationDate"]/@content' ),
        ( None, '//meta[@name="article_date_original"]/@content' ),
        ( None, '//meta[@name="publication_date"]/@content' ),
        ( None, '//meta[@name="sailthru.date"]/@content' ),
        ( None, '//meta[@name="PublishDate"]/@content' ),
        ( None, '//meta[@name="all_timestamps"]/@content' ),
        ( None, '//meta[@name="dc.Date"]/@content' ),
        ( None, '//meta[@name="cXenseParse:recs:publishtime"]/@content' ),

        # microdata paths
        ( None, '//*[@itemprop="datePublished"]/@content' ),
        ( None, '//*[@itemprop="datePublished"]/@datetime' ),
        #( None, '//*[@itemprop="datePublished"]' ),
        ( None, '//*[@property="datePublished"]/@content' ),
        ( None, '//*[@property="datePublished"]/@datetime' ),
        #( None, '//*[@property="datePublished"]' ),

        # custom xpaths
        ( 'actualidad.rt.com',              '//div[@class="ArticleView-timestamp"]/time/@datetime' ),
        ( 'angrystaffofficer.com',          '//time[contains(@class,"published")]' ),
        ( 'armscontrolwonk.com',            '//span[@class="date published time"]' ),
        ( 'bbc.com',                        '(//div[@class="date date--v2"])[1]' ),
        ( 'bbc.co.uk',                      '(//div[@class="date date--v2"])[1]' ),
        ( 'bles.com',                       '(//span[@class="p-time"]/@data-date)[1]' ),
        ( 'csis.org',                       '//article[@role="article"]/p' ),
        ( 'elheraldo.co',                   '(//div[@class="datos"]/time/@datetime)[1]' ),
        ( 'elperuano.pe',                   '//article[@class="notatexto"]/p/b' ),
        ( 'elnacional.com.do',              '(//time[contains(@class,"entry-date")])[1]' ),
        ( 'english.khan.co.kr',             '//div[@class="article_date"]' ),
        ( 'foxnews.com',                    '//div[@class="article-date"]/time' ),
        ( 'headtopics.com',                 '//meta[@name="date"]/@content' ), # FIXME: English articles use MDY, but Spanish articles use DMY
        #( 'headtopics.com',                 '//div[@class="Article-readingTime"]' ), # FIXME: English articles use MDY, but Spanish articles use DMY
        ( 'laregion.es',                    '//meta[@name="date"]/@content' ),
        ( 'mundiario.com',                  '//span[@class="content-time"]' ),
        ( 'nytimes.com',                    '//meta[@property="article:published"]/@content' ),
        ( 'reuters.com',                    '//time' ),
        ( 'spiegel.de',                     '//span[@class="article-function-date"]/b' ),
        ( 'spiegel.de',                     '//time/@datetime' ),
        ( 'stripes.com',                    '//span[@class="published_date"]' ),
        ( 'thediplomat.com',                '//span[@itemprop="datePublished"]' ),
        ( 'theintercept.com',               '//span[@class="PostByline-date"]' ),
        ( 'time.com',                       '//div[contains(@class,"published-date")]' ),
        ( 'voxeurop.eu',                    '//div[contains(@class,"publish_date_time")]' ),
        ( 'wsj.com',                        '//time' ),
        ]

    return get_timestamp(html, url, xpaths, use_url_date=True, **kwargs)


def get_timestamp_modified(html, url, **kwargs):
    '''
    Returns a timestamp dictionary that the input webpage was modified/updated on.

    See get_timestamp for details about the timestamp dictionary.
    '''
    xpaths = [
        # meta xpaths
        ( None, '//meta[@property="rnews:dateModified"]/@content' ),
        ( None, '//meta[@property="article:modified_time"]/@content' ),
        ( None, '//meta[@property="og:modified_time"]/@content' ),

        # microdata paths
        ( None, '//*[@itemprop="dateModified"]/@content' ),
        ( None, '//*[@itemprop="dateModified"]/@datetime' ),
        ( None, '//*[@itemprop="dateModified"]' ),
        ( None, '//*[@property="dateModified"]/@content' ),
        ( None, '//*[@property="dateModified"]/@datetime' ),
        ( None, '//*[@property="dateModified"]' ),

        # xpaths
        ( 'angrystaffofficer.com',          '//time[contains(@class,"updated")]' ),
        ( 'foxnews.com',                    '//div[@class="article-updated"]' ),
        ( 'nytimes.com',                    '//meta[@property="article:modified"]/@content' ),
        ]
    return get_timestamp(html, url, xpaths, use_url_date=False, **kwargs)


def get_timestamp(html, url, xpaths, use_url_date=False, require_valid_for_hostname=True, fast=True):
    '''
    FIXME: make the xpath code faster using
    https://www.ibm.com/developerworks/xml/library/x-hiperfparse/
    '''
    parser = lxml.html.fromstring(html)
    url_parsed = urlparse(url)
    url_hostname = url_parsed.hostname

    timestamps = []

    # get timestamp from url
    if use_url_date:
        _STRICT_DATE_REGEX_PREFIX = r'(?<=\W)'
        DATE_REGEX = r'(([\./\-_]{0,1}(19|20)\d{2})[\./\-_]{0,1}(([0-3]{0,1}[0-9][\./\-_])|(\w{3,5}[\./\-_]))([0-3]{0,1}[0-9][\./\-]{0,1})?)...'
        STRICT_DATE_REGEX = _STRICT_DATE_REGEX_PREFIX + DATE_REGEX
        date_match = re.search(STRICT_DATE_REGEX, url)
        if date_match:
            timestamp_str = date_match.group(1)
            timestamp = parse_timestamp_str(timestamp_str)
            timestamp['is_valid_for_hostname'] = True
            timestamp['pattern'] = ['url']
            timestamps.append(timestamp)

    # get timestamps from xpaths
    for hostname,xpath in xpaths:

        # if in fast mode, then only search for elements that will apply to the hostname
        valid_for_hostname = hostname is None or hostname in url_hostname
        if fast and not valid_for_hostname:
            continue

        # loop through all elements found by the xpath
        for element in parser.xpath(xpath):

            # element can be one of several different types of lxml objects;
            # depending on the type, we need to extract the text in different ways
            if type(element) is lxml.etree._ElementUnicodeResult:
                timestamp_str = str(element)
            elif type(element) is lxml.etree._Element:
                timestamp_str = element.text
            elif type(element) is lxml.html.HtmlElement:
                timestamp_str = element.text_content()

            # generate the timestamp from text
            timestamp = parse_timestamp_str(timestamp_str)
            if timestamp is not None:
                timestamp['is_valid_for_hostname'] = valid_for_hostname
                timestamp['pattern'] = xpath
                timestamps.append(timestamp)

                # NOTE:
                # the following check is tempting but wrong;
                # we need to ensure that pages with many urls 
                # get treated as categories and not articles
                #if valid_for_hostname and fast:
                    #break

    # extract the best timestamp from the list of available timestamps
    best_timestamps = get_best_timestamps(timestamps)

    return best_timestamps, timestamps
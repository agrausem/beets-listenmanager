from collections import namedtuple
import os.path
from datetime import date
from functools import partial, wraps
import re
from beets.dbcore import types
from beets.library import Album, parse_query_string
from beets.plugins import BeetsPlugin
from beets import config
from beets.mediafile import (
    MediaField, MP3DescStorageStyle, MP4StorageStyle, ASFStorageStyle,
    StorageStyle, MediaFile
)
from beets import ui
from beets.ui import print_
from beets.util import mkdirall, normpath, sanitize_path, syspath


def update_and_diff(album, mods):
    """ Update the album, print the modifications and return a bool indicating
    whether any changes were made.
    """
    album.update(mods)
    return ui.show_model_changes(album)


class ChangeCmd():

    _TODAY = date.today()
    DEFAULT_YEAR = str(_TODAY.year)
    DEFAULT_MONTH = str(_TODAY.month)

    def __init__(self, args, opts, pl_template, pl_pattern, defaults=True):
        self._query, self._playlists = [], []
        self._pattern = re.compile(pl_pattern)
        print(pl_pattern)
        self._defaults = defaults

        for arg in args:
            if arg.startswith('@'):
                print(arg[1:], self._pattern.match(arg[1:]))
                if self._pattern.match(arg[1:]):
                    self._playlists.append(arg[1:])
            else:
                self._query.append(arg)

        self._opts = opts
        self._pl_template = pl_template
        print(self._playlists, self._query)

    @property
    def query(self):
        return ui.decargs(self._query)

    @property
    def write(self):
        return ui.should_write(self._opts.write)

    @property
    def move(self):
        return ui.should_move(self._opts.move)

    @property
    def confirm(self):
        return not self._opts.yes

    @property
    def playlists(self):
        if self._defaults:
            return self._playlists or [self.default_playlist]
        return self._playlists

    @property
    def default_playlist(self):
        return self._pl_template.format(self.DEFAULT_YEAR, self.DEFAULT_MONTH)


class PlaylistDescriptor(namedtuple('PlaylistDescriptor', 'name q')):

    @property
    def query(self):
        return parse_query_string(self.q, Album)[0]

    @property
    def sort(self):
        return parse_query_string(self.q, Album)[1]

    @property
    def query_and_sort(self):
        return parse_query_string(self.q, Album)


class ListenPlugin(BeetsPlugin):

    YEAR_PATTERN = '[1-2][0-9]{3}'
    MONTH_PATTERN = '[1-2][0-9]{3}-(?:0[0-9]|1[0-2])'

    def __init__(self):
        # TODO: better config
        super(ListenPlugin, self).__init__()

        self.config.add({
            'pl_tag_template': '{0}-{1:>02}',
            'pl_tag_separator': ',',
            'relative': None,
            'playlist_dir': u'.',
            'auto': True,
        })

        self._matched_playlists = set()
        self._special_playlists = {
            PlaylistDescriptor(
                'by_month', 'playlists::%s' % self.MONTH_PATTERN
            ),
            PlaylistDescriptor(
                'by_year', 'playlists::%s' % self.YEAR_PATTERN
            )
        }

        if self['auto']:
            self.register_listener('database_change', self.db_change)

    def __getitem__(self, config_name):
        return self.config[config_name]

    @property
    def album_types(self):
        return {
            'listen': types.BOOLEAN,
            'playlists': types.STRING,
            'plays_nb': types.INTEGER
        }

    def commands(self):
        add_playlist_cmd = ui.Subcommand(
            'ltaadd', help='add album to playlist'
        )
        add_playlist_cmd.parser.add_option(
            u'-m', u'--move', action='store_true', dest='move',
            help=u"move files in the library directory"
        )
        add_playlist_cmd.parser.add_option(
            u'-M', u'--nomove', action='store_false', dest='move',
            help=u"don't move files in library"
        )
        add_playlist_cmd.parser.add_option(
            u'-w', u'--write', action='store_true', default=None,
            help=u"write new metadata to files' tags (default)"
        )
        add_playlist_cmd.parser.add_option(
            u'-W', u'--nowrite', action='store_false', dest='write',
            help=u"don't write metadata (opposite of -w)"
        )
        add_playlist_cmd.parser.add_option(
            u'-y', u'--yes', action='store_true',
            help=u'skip confirmation'
        )
        add_playlist_cmd.func = self.add_playlist

        remove_playlist_cmd = ui.Subcommand(
            'ltarm', help='remove playlist from album'
        )
        remove_playlist_cmd.parser.add_option(
            u'-m', u'--move', action='store_true', dest='move',
            help=u"move files in the library directory"
        )
        remove_playlist_cmd.parser.add_option(
            u'-M', u'--nomove', action='store_false', dest='move',
            help=u"don't move files in library"
        )
        remove_playlist_cmd.parser.add_option(
            u'-w', u'--write', action='store_true', default=None,
            help=u"write new metadata to files' tags (default)"
        )
        remove_playlist_cmd.parser.add_option(
            u'-W', u'--nowrite', action='store_false', dest='write',
            help=u"don't write metadata (opposite of -w)"
        )
        remove_playlist_cmd.parser.add_option(
            u'-y', u'--yes', action='store_true',
            help=u'skip confirmation'
        )
        remove_playlist_cmd.func = self.remove_playlist

        update_playlists_cmd = ui.Subcommand(
            'ltagen',
            help=('generate or update the listen playlists. '
                  'Playlist names may be passed as arguments.')
        )
        update_playlists_cmd.func = self.update_playlists

        return [add_playlist_cmd, remove_playlist_cmd, update_playlists_cmd]

    def _init_change_cmd(self, lib, args, opts, fmods_name):
        self._library = lib
        self._cmd = ChangeCmd(
            args, opts, self['pl_tag_template'].get(), self.MONTH_PATTERN
        )
        self._mods_func = getattr(self, fmods_name)

    def _init_gen_cmd(self, lib):
        self._library = lib
        self._playlist_dir = self['playlist_dir'].as_filename()
        self._relative = self['relative'].get(bool)
        self._year_expression = re.compile(r'(%s)' % self.YEAR_PATTERN)
        self._month_expression = re.compile(r'(%s)' % self.MONTH_PATTERN)

    def db_change(self, lib, model):

        for pl in self._special_playlists:
            match = isinstance(model, Album) and pl.query.match(model)
            if match:
                self._log.debug(
                    u"{0} will be updated because of {1}", pl.name, model)
                self._matched_playlists.add(pl)
                self.register_listener('cli_exit', self.generate_playlists)

        self._special_playlists -= self._matched_playlists

    def get_m3u_files(self):
        for top, _, filenames in os.walk(self._playlist_dir):
            for filename in filenames:
                yield os.path.join(os.path.basename(top), filename)

    def album_mods(self, album):
        actual_playlists = set(
            album.playlists.split(self['pl_tag_separator'].get())
            if getattr(album, 'playlists', '')
            else []
        )
        playlists = actual_playlists.union(set(self._cmd.playlists))
        plays_nb = len(playlists)
        return {
            'listen': True,
            'playlists': ','.join(sorted(playlists)),
            'plays_nb': plays_nb
        }

    def playlists_mods(self, album):
        old_playlists = set(
            album.playlists.split(self['pl_tag_separator'].get())
        )
        new_playlists = old_playlists - set(self._cmd.playlists)
        return {
            'listen': bool(new_playlists),
            'playlists': ','.join(sorted(new_playlists)),
            'plays_nb': len(new_playlists)
        }

    def album_changes(self):
        albums = self._library.albums(self._cmd.query)
        ui.print_('Modifying {0} {1}s.'.format(len(albums), 'album'))
        return {
            album for album in albums
            if update_and_diff(album, self._mods_func(album))
        }

    def show_changes(self, changed):
        if self._cmd.write and self._cmd.move:
            extra = u', move and write tags'
        elif self._cmd.write:
            extra = u' and write tags'
        elif self._cmd.move:
            extra = u' and move'
        else:
            extra = u''

        return ui.input_select_objects(
            u'Really modify%s' % extra, changed,
            lambda a: update_and_diff(a, self._mods_func(a))
        )

    def save(self, albums):
        with self._library.transaction():
            for album in albums:
                album.try_sync(self._cmd.write, self._cmd.move)

    def add_playlist(self, lib, opts, args):
        """
        """
        self._init_change_cmd(lib, args, opts, 'album_mods')
        changed = self.album_changes()

        # Still something to do?
        if not changed:
            print_(u'No changes to make.')
            return

        # Confirm action.
        if self._cmd.confirm:
            changed = self.show_changes(changed)

        self.save(changed)

    def remove_playlist(self, lib, opts, args):
        """
        """
        self._init_change_cmd(lib, args, opts, 'playlists_mods')
        changed = self.album_changes()

        # Still something to do?
        if not changed:
            print_(u'No changes to make.')
            return

        # Confirm action.
        if self._cmd.confirm:
            changed = self.show_changes(changed)

        self.save(changed)

    def update_playlists(self, lib, opts, args):
        # TODO: add args
        self._matched_playlists = self._special_playlists
        self.generate_playlists(lib)

    def _by_month(self, playlist_name):
        year, month = playlist_name.split('-')
        m3u_path = date(int(year), int(month), 1).strftime('%Y/%m %B.m3u')
        return sanitize_path(m3u_path, self._library.replacements)

    def _by_year(self, playlist_name):
        m3u_path = f'{playlist_name}/00 All.m3u'
        return sanitize_path(m3u_path, self._library.replacements)

    def _pl_by_month(self, album_pls):
        return [
            self._by_month(pl)
            for pl in self._month_expression.findall(album_pls)
            if pl
        ]

    def _pl_by_year(self, album_pls):
        return [
            self._by_year(pl)
            for pl in sorted(set(self._year_expression.findall(album_pls)))
            if pl
        ]

    def _get_relative_path(self, item_path, playlist_name):
        playlist_base_dir = os.path.dirname(playlist_name)
        playlist_path = os.path.join(self._playlist_dir, playlist_base_dir)
        return os.path.relpath(item_path, normpath(playlist_path))

    def get_playlist_items(self, playlist_desc):
        get_pls = getattr(self, f'_pl_{playlist_desc.name}')
        for album in self._library.albums(*playlist_desc.query_and_sort):
            album_playlists = get_pls(getattr(album, 'playlists', ''))
            for album_playlist in album_playlists:
                yield album_playlist, album.items()

    def get_item_path(self, item, playlist_name):
        if self._relative:
            return self._get_relative_path(item.path, playlist_name)
        return item.path

    def m3us(self):
        m3us = {}
        for pls_desc in self._matched_playlists:
            self._log.debug(u"Creating playlist {0}", pls_desc.name)
            pls_items = self.get_playlist_items(pls_desc)
            for pl_name, items in pls_items:
                for item in items:
                    item_path = self.get_item_path(item, pl_name)
                    m3us.setdefault(pl_name, []).append(item_path)
        return m3us

    def get_m3u_path(self, m3u):
        m3u_path = normpath(os.path.join(self._playlist_dir, m3u))
        mkdirall(m3u_path)
        return m3u_path

    def generate_playlists(self, lib):
        self._init_gen_cmd(lib)
        self._log.info(u"Updating {0} smart playlists…",
                       len(self._matched_playlists))

        m3us = self.m3us()
        for m3u, paths in m3us.items():
            with open(syspath(self.get_m3u_path(m3u)), 'wb') as f:
                for path in paths:
                    f.write(path + b'\n')

        self._log.info(u"{0} playlists updated", len(m3us))

        self.remove_playlist_files(m3us)

    def remove_playlist_files(self, m3us):
        m3u_files = set(self.get_m3u_files())
        self._log.info(f'Scanning {len(m3u_files)} playlist files…')
        orphans = set(m3us).symmetric_difference(m3u_files)

        if not orphans:
            self._log.info('All playlists are fine.')
            return

        self._log.info(f'{len(orphans)} orphan playlist found\n')
        for pl in orphans:
            self._log.info(ui.colorize('text_highlight', pl))

        # self.remove(orphans)

    def remove(self, orphans):
        for playlist in orphans:
            pl_path = os.path.join(self._playlist_dir, playlist)
            os.remove(pl_path)

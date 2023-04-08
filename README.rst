beets-listenmanager
===================

Beets plugin to manage playlists and listen property

Installation
-------------

To add the plugin, edit the ``beet``'s configuration file and add ``listenmanager`` to the list of ``plugins``


Configuration
-------------

Create a ``listenmanager`` entry in the ``beet``'s configuration file and edit the following parameters

``pl_tag_template`` : ``{0}-{1:>02}``

The format for storing playlists based on year and month into the database.
This is the format to pass playslist as argument for commands. ``0`` is year and ``1`` is month. 

``pl_tag_separator`` :  ``,``

The separator for storing multiple playlists in the ``playlists`` album field.


``relative`` : ``no`` 

Should playlists be generated with relative path to library path.


``playlist_dir`` : current directory

Define the playlists base directory


``auto`` : ``yes``

Launch playlists generation on every database change


``remove_orphans`` : ``no``

Remove playlists that contain no album


Commands
--------

``ltaadd``

Add album(s) to a playlist and generate or update the m3u file.

Example : ::

    beet ltaadd album:"ride the lightning" @2012-06


This will add the album *Metallica - Ride the Lightning* to the *2012-06* playlists and
create or update the ``2012/06 June.m3u`` file


``ltagen``

Generate the m3u file(s) from the ``playlists`` field in database.
If ``remove_orphans`` is activated, this will remove playlists with no album. 

Example : ::

    beet ltagen

``ltarm``

Delete album(s) from a playlist and update the m3u file

Example : ::

    beet ltarm album:"ride the lightning" @2012-06

This will remove the album *Metallica - Ride the Lightning* to the *2012-06* playlists and
update the ``2012/06 June.m3u`` file. **This command will never remove an m3u file.**

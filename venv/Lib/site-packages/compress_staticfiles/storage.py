import os
import binascii
import copy
import json
import gzip
import brotli
from io import BytesIO

from django.contrib.staticfiles.storage import (
    StaticFilesStorage, ManifestFilesMixin
)
from django.conf import settings
from django.core.files.base import ContentFile

from csscompressor import compress
from rjsmin import jsmin as rjsmin

from . import utils


class MinifyFilesMixin:

    def _minify_js(self, path):
        """
        Will keep bang/exclamation comments.
        """
        # FileSystemStorage makes path absolute
        with self.open(path, 'rb') as js_file:
            minified_text = rjsmin(
                js_file.read().decode('utf-8'),
                keep_bang_comments=True,
            )
        return minified_text

    def _minify_css(self, path):
        """
        Will keep bang/exclamation comments.
        """
        with self.open(path, 'rb') as css_file:
            minified_text = compress(
                css_file.read().decode('utf-8'),
                preserve_exclamation_comments=True,
            )
        return minified_text

    def minify(self, path, dry_run=False):
        """
        Minify a CSS or JS file and return a tuple of the built filepath
        and the minified text: (new_filepath, minified_text). Does not write
        anything to a file.

        The built filepath is a filepath containing a new hash of the file's
        contents and is in the following format: filename.min.{hash}.css.
        This is just a filepath you *could* use to save the file.

        Will work with whichever storage it is hooked up to.
        Will keep bang/exclamation comments.

        Arguments:
        path    -- Accepts a relative or absolute path pointing to the file to
                   be be minified.
        dry_run -- Boolean, if True, no file will be opened or written to.

        Returns:
        - Will return None if dry_run is True.
        - Will return None if file is not a minifiable filetype - JS and CSS only.
        - A tuple of the built filepath containing the newly built filename for
          the minified file (containing a new md5 filehash) and the minified
          text: (new_filepath, minified_text).
        """
        if '.min' in path or dry_run:
            # Don't re-minify minified files
            return None

        minifiable_types = {
            '.css',
            '.js',
        }
        minified_text = None
        new_filepath = None

        root, filename = os.path.split(path)
        split_filename = filename.split('.')
        # Can't use splitext because that might split the extension as
        # something like .gz or .br instead of .css
        ext = split_filename[-1] # will always be last.
        ext = utils.normalize_ext(ext) # add the dot (.css not css)
        filename_without_ext = split_filename[0] # will always be first

        if ext in minifiable_types:
            if ext == '.css':
                minified_text = self._minify_css(path)
            elif ext == '.js':
                minified_text = self._minify_js(path)

            # Check if a hash is present in input filepath.
            # If so, re-hash the new minified file.
            hash = utils.get_filehash_in_filename(path)
            if hash:
                hash = utils.make_file_hash(minified_text, filename_without_ext)

            new_filename = utils.build_filename(
                filename_without_ext=filename_without_ext,
                extension=ext,
                minify=True,
                hash=hash,
            )
            new_filepath = os.path.join(root, new_filename)

        return new_filepath, minified_text


class CompressStaticFilesMixin:
    """
    Filetypes that must never be processed by this class:
    - .jpg
    - .jpeg
    - .webp
    - .png
    - .tiff
    - .bmp
    - .gif
    - .woff
    - .gz
    - .br
    - .zip
    - .rar
    """
    included_filetypes = {
        '.css',
        '.js',
        '.txt',
        '.xml',
        '.json',
        '.svg',
        '.md',
        '.rst',
    }

    def __init__(self, *args, **kwargs):
        if not hasattr(settings, 'MINIFY_STATIC'):
            settings.MINIFY_STATIC = True

        if not hasattr(settings, 'BROTLI_STATIC_COMPRESSION'):
            settings.BROTLI_STATIC_COMPRESSION = True

        if not hasattr(settings, 'GZIP_STATIC_COMPRESSION'):
            settings.GZIP_STATIC_COMPRESSION = True

        self.MINIMUM_SIZE_FOR_COMPRESSION = 200
        super().__init__(*args, **kwargs)


    def post_process(self, paths, dry_run=False, *args, **kwargs):
        """
        To summarise, while ignoring some detail, this is what happens here:

        Part 1:
        - Let ManifestFilesMixin do it's job by calling super.
        - All static files, as they were found by the static file finders,
          should now be copied over to the STATIC_ROOT and the
          ManifestFilesMixin would have created a manifest file to map the
          static files to their newly created hashed versions.

        Part 2:
        - Read from the manifest file.
        - Iterate through all the paths found in the manifest file.
        - Build the minification_set.
        - Partially build the compression_set - items in minification_set still
          need to be added once they've been created when processing the
          items in the minification_set.

        Part 3:
        - Minify all files in minification_set.

        Part 4:
        - Compress all files in compression_set

        Part 5:
        - Update the manifest file.

        Note:
        - The "origin/source" means where the static file finders found the
          static files.
        - The "destination/target" means where the staticfiles storage copies
          the files to. This is STATIC_ROOT.
        - The source storage of each found static file is included in the
          paths argument.
        """
        if dry_run:
            # If we don't return immediately (before super) the
            # ManifestFilesMixin creates the staticfiles.json manifest file.
            self.log(
                '\nPretending to post-process static files with '
                'compress_staticfiles...'
            )
            return

        # Whether we get the files that were processed by ManifestFilesMixin
        # by calling super() or whether we get them from the manifest file
        # makes no difference - we have to open the manifest file anyway
        # because we need to update the paths stored inside it.
        yield from super().post_process(paths, dry_run, *args, **kwargs)

        try:
            # if the manifest isn't found read_manifest()
            # will return None but let's rather be safe.
            manifest_json = self.read_manifest()
        except FileNotFoundError:
            manifest_json = None

        if manifest_json is None:
            raise Exception('Manifest file is missing')
        manifest_dict = json.loads(manifest_json)

        # sets of tuples: {(non_hashed_file_filepath, hashed_file_filepath)}
        # Include the non_hashed_file in the tuple because we need to do
        # a lookup on the paths argument later to get the source_path and
        # source_storage so that we can check if the file is stale. Stale
        # means that the origin file has been changed.
        compression_set = set() # all the files to be compressed go here
        minification_set = set() # all the files to be minified go here
        amount_of_files_in_manifest = len(manifest_dict['paths'])
        updated_paths = copy.deepcopy(manifest_dict['paths'])


        self.log(
            '\n\nPost-processing files with compress_staticfiles...\n'
        )
        self.log(
            '\nChecking which files to minify and compress...'
            + ' '
            + '(' + str(amount_of_files_in_manifest)
            + ' items in the manifest'
            + ')\n'
        )


        file_counter = 0
        # non_hashed_file and hashed_file are both relative paths
        for non_hashed_file, hashed_file in manifest_dict['paths'].items():
            file_counter += 1
            percentage = round((file_counter / amount_of_files_in_manifest) * 100, 2)
            self._log_progress(percentage, file_counter, amount_of_files_in_manifest)

            ext = os.path.splitext(non_hashed_file)[1]
            if (ext not in self.included_filetypes):
                self.log(('Skipping excluded filetype: ' + ext))
                continue

            if ('.min' not in non_hashed_file) and (settings.MINIFY_STATIC):
                # We don't process the non-hashed versions of minified files.
                # If we did though, we would have to make sure that we don't
                # overwrite minified files that came from the origin.
                minification_set.add((non_hashed_file, hashed_file))

            if '.min' in non_hashed_file:
                # This is a min file from the origin, compress it and it's
                # hashed version. Only process the non-hashed version of the
                # file when it is a minified file from the origin.
                if settings.GZIP_STATIC_COMPRESSION or settings.BROTLI_STATIC_COMPRESSION:
                    compression_set.add((non_hashed_file, non_hashed_file))
                    compression_set.add((non_hashed_file, hashed_file))

            # Add to compression_set here to catch the hashed versions
            # of normal files, for example: example.{hash}.css
            if settings.GZIP_STATIC_COMPRESSION or settings.BROTLI_STATIC_COMPRESSION:
                compression_set.add((non_hashed_file, hashed_file))


        # Minify files in minification_set
        if not minification_set:
            self.log('\n\nNo files to minify.')
        else:
            self.log('\n\nMinifying files...')
            file_counter = 0
            for non_hashed_file, hashed_file_fp in minification_set:
                file_counter += 1
                amount_files_to_minify = len(minification_set)
                percentage = round((file_counter / amount_files_to_minify) * 100, 2)
                self._log_progress(percentage, file_counter, amount_files_to_minify)

                hashed_min_fp, minified_text = self.minify(
                    hashed_file_fp,
                    dry_run=dry_run,
                )
                processed = False
                processed_name = hashed_file_fp
                if hashed_min_fp and minified_text is not None:
                    source_storage, source_path = paths[os.path.normpath(non_hashed_file)]
                    if self._is_modified_file(source_path, hashed_min_fp, source_storage):
                        self.save(hashed_min_fp, ContentFile(minified_text.encode('utf-8')))
                        compression_set.add((non_hashed_file, hashed_min_fp))
                        processed = True # mark as processed

                    if hashed_min_fp:
                        updated_paths[non_hashed_file] = hashed_min_fp.replace('\\', '/')
                        processed_name = hashed_min_fp

                    processed_name = hashed_min_fp
                yield non_hashed_file, processed_name, processed


        # Compress files in compression_set
        if not compression_set:
            self.log('\n\nNo files to compress.')
        else:
            self.log('\n\nCompressing files...')
            file_counter = 0
            for non_hashed_file, filepath in compression_set:
                file_counter += 1
                amount_of_files_to_compress = len(compression_set)
                percentage = round((file_counter / amount_of_files_to_compress) * 100, 2)
                self._log_progress(percentage, file_counter, amount_of_files_to_compress)

                source_storage, source_path = paths[os.path.normpath(non_hashed_file)]
                if filepath:
                    if settings.GZIP_STATIC_COMPRESSION:
                        if self._is_modified_file(
                            source_path,
                            (filepath + '.gz'),
                            source_storage
                        ):
                            # Files smaller than MINIMUM_SIZE_FOR_COMPRESSION
                            # will not be skipped because they don't exist
                            self.gzip_compress(filepath)

                    if settings.BROTLI_STATIC_COMPRESSION:
                        if self._is_modified_file(
                            source_path,
                            (filepath + '.br'),
                            source_storage
                        ):
                            # Files smaller than MINIMUM_SIZE_FOR_COMPRESSION
                            # will not be skipped because they don't exist
                            self.brotli_compress(filepath)


        # Update manifest file
        #
        # Update the manifest file with hashed-and-minified version of the file.
        # For example: example.css would point to example.min.{hash}.css
        # We need to do this every time collectstatic runs because
        # ManifestFilesMixin will keep resetting our values.
        # Get manifest_name from ManifestFilesMixin.
        # https://github.com/django/django/blob/master/django/contrib/staticfiles/storage.py
        self.log('\n\nUpdating manifest file...\n')
        manifest_dict['paths'] = updated_paths
        if self.exists(self.manifest_name):
            self.delete(self.manifest_name)
        new_manifest_contents = json.dumps(manifest_dict).encode()
        self.save(self.manifest_name, ContentFile(new_manifest_contents))


    def log(self, msg):
        print(msg)


    def _log_progress(self, percentage, current_file, total_files):
        percentage = str(percentage)
        current_file = str(current_file)
        total_files = str(total_files)
        progress_msg = percentage + '% -- ' + current_file + '/' + total_files
        self.log(progress_msg)


    def _is_modified_file(
            self, source_path, target_path, source_storage, dry_run=False):
        """
        Check if the file from the origin (source_path) has been modified by
        comparing the modified times of the source_path and the target_path.
        """
        if self.exists(target_path) and source_storage.exists(source_path):
            try:
                target_last_modified = self.get_modified_time(target_path)
            except (OSError, NotImplementedError, AttributeError):
                # play it safe, assume the target is stale, don't do anything
                pass
            else:

                try:
                    source_last_modified = source_storage.get_modified_time(source_path)
                except (OSError, NotImplementedError, AttributeError):
                    # play it safe, assume the target is stale, don't do anything
                    pass
                else:
                    file_is_unmodified = (
                        target_last_modified.replace(microsecond=0) >=
                        source_last_modified.replace(microsecond=0)
                    )

            if file_is_unmodified:
                self.log("Skipping '%s' (origin not modified)" % target_path)
                return False

            if not dry_run:
                self.log("Deleting '%s'" % target_path)
                if self.exists(target_path):
                    self.delete(target_path)
        return True


    def gzip_compress(self, filepath):
        """
        Compress a file with Gzip. Save it to the same directory as the
        input filepath.

        Returns the input filepath + '.gz'
        """
        GZIP_MAGIC_NUMBER = '1f8b'
        ext = os.path.splitext(filepath)[1]

        # Check 1: Make sure the extension is okay
        if ext not in self.included_filetypes:
            return None

        new_filepath = filepath + '.gz'

        with self.open(filepath, 'rb') as in_file:
            # Check 2: Check that the in_file isn't already gzip compressed
            hex = binascii.hexlify(in_file.read(2))
            in_file.seek(0)

            if hex == GZIP_MAGIC_NUMBER:
                return None

            # Check 3: If the file is smaller than MINIMUM_SIZE_FOR_COMPRESSION
            # compression can be ineffective resulting in a larger file
            # instead of a smaller one.
            if len(in_file.read()) < self.MINIMUM_SIZE_FOR_COMPRESSION:
                return None

            in_file.seek(0)
            stream = BytesIO()
            gzip_file = gzip.GzipFile(
                mode='wb',
                compresslevel=9,
                fileobj=stream,
            )
            gzip_file.write(in_file.read()) # write to stream
            gzip_file.close()
            if self.exists(new_filepath):
                self.delete(new_filepath)
            self.save(new_filepath, ContentFile(stream.getvalue()))
            stream.close()
        return new_filepath


    def brotli_compress(self, filepath):
        """
        Compress a file with Brotli. Save it to the same directory as the
        input filepath.

        Returns the input filepath + '.br'
        """
        ext = os.path.splitext(filepath)[1]

        # Check 1: Make sure the extension is okay
        if ext not in self.included_filetypes:
            return None

        new_filepath = filepath + '.br'

        in_file_content = None
        with self.open(filepath, 'rb') as in_file:
            in_file_content = in_file.read()

            # Check 2: Check that the file isn't already brotli-compressed.
            # Brotli has no magic number like gzip, but when we try to
            # decompress a non-compressed file Brotli throws an error.
            try:
                brotli.decompress(in_file_content)
            except brotli.error: # BrotliDecompress failed
                # file is not compressed
                in_file.seek(0)
            else:
                # file is compressed: don't re-compress it
                return None

            # Check 3: If the file is smaller than MINIMUM_SIZE_FOR_COMPRESSION
            # compression can be ineffective resulting in a larger file
            # instead of a smaller one.
            if len(in_file_content) < self.MINIMUM_SIZE_FOR_COMPRESSION:
                return None

            compressed_contents = brotli.compress(in_file_content, quality=11)
            if self.exists(new_filepath):
                self.delete(new_filepath)
            self.save(new_filepath, ContentFile(compressed_contents))
        return new_filepath


class CompressStaticFilesStorage(
        CompressStaticFilesMixin, MinifyFilesMixin, ManifestFilesMixin,
        StaticFilesStorage):
    """
    A static files storage backend for compression using GZip and/or Brotli
    that inherits from Django's ManifestFilesMixin and StaticFilesStorage;
    also minifies static files.
    """
    pass

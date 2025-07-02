import os
import hashlib


def make_file_hash(content, filename):
    """
    Return an md5 hash of content. Use the filename as a backup if
    content is None.
    """
    md5 = hashlib.md5()
    if content is None or len(content) == 0:
        content = filename
    md5.update(content.encode('utf-8'))
    # keep the length of the hash consistent with the length Django uses
    return md5.hexdigest()[:12]


def get_filehash_in_filename(path):
    """
    Return the filehash, created by Django's ManifestFilesMixin, present
    in a filename.
    """
    hash = None
    filename = os.path.split(path)[1]
    for part in filename.split('.'):
        if len(part) == 12:
            hash = part
    return hash


def build_filename(
        filename_without_ext, extension, minify=None, hash=None,
        brotli=False, gzip=False):
    """
    In format: {filename}.min.{hash}.{extension}.{encoding_extension}

    Keep the format of how the file is built consistent with how Django's
    ManifestFilesMixin does it. Switching between different ways of building
    the file would just make things confusing and possibly cause problems.
    """
    filename = filename_without_ext
    if minify:
        filename += '.min'
    if hash:
        filename += '.' + hash
    if extension:
        extension = normalize_ext(extension)
        filename += extension
    return filename


def normalize_ext(ext):
    """
    Add a dot to normalize extension: .css not css
    """
    if ext[0] != '.':
        ext = '.' + ext
    return ext

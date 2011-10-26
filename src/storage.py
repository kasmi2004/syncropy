# -*- coding: utf-8 -*-
"""
Copyright (C) 2010 Enrico Bianchi (enrico.bianchi@gmail.com)
Project       Syncropy
Description   A backup system
License       GPL version 2 (see GPL.txt for details)
"""

__author__ = "enrico"

from datetime import datetime

import logging
import os
import shutil
import src.db
import src.queries

class DbStorage(object):
    _cfg = None

    _con = None
    _oldcon = None
    _syscon = None

    _dataset = None
    _mode = None
    _logger = None
    _section = None

    def __init__(self, cfg):
        self._cfg = cfg

        dbm = src.db.DBManager(self._cfg)
        self._logger = logging.getLogger("Syncropy")
        self._syscon = dbm.open(self._cfg.get("general", "repository") + "/.syncropy.db", system=True)

    def __del__(self):
        try:
            if self._syscon:
                self._syscon.commit()
                self._syscon.close()

            if self._con:
                self._con.commit()
                self._con.close()

            if self._oldcon:
                self._oldcon.rollback()
                self._oldcon.close()
        except:
            pass

    def _add_acl(self, item, acl, idtype):
        ins = src.queries.Insert("?")

        ins.set_table("acls")
        ins.set_data(element=item.decode("utf-8"),
                    perms=acl["attrs"])

        if idtype == "u":
            ins.set_data(id=acl["uid"],
                    id_type=idtype)
        else:
            ins.set_data(id=acl["gid"],
                    id_type=idtype)

        ins.build()

        try:
            cur = self._con.cursor()
            cur.execute(ins.get_statement(), ins.get_values())
            cur.close()
        except Exception as ex:
            self._logger.error("Error whilea add acl for " + item + " into database")
            for error in ex:
                if type(error) in [str, int]:
                    self._logger.error("    " + str(error))
                else:
                    for line in error:
                        self._logger.error("    " + line)

    def _add_element(self, element, attributes):
        ins = src.queries.Insert("?")
        ins.set_table("attrs")
        ins.set_data(element=element.decode("utf-8"),
                     element_user=attributes["user"],
                     element_group=attributes["group"],
                     element_ctime=attributes["ctime"],
                     element_mtime=attributes["mtime"])

        if attributes["type"] == "pl":
            ins.set_data(element_type="f")
        else:
            ins.set_data(element_type=attributes["type"])

        ins.build()
        try:
            cur = self._con.cursor()
            cur.execute(ins.get_statement(), ins.get_values())
            cur.close()
        except Exception as ex:
            self._logger.error("Error whilea add element " + element + " into database")
            for error in ex:
                if type(error) in [str, int]:
                    self._logger.error("    " + str(error))
                else:
                    for line in error:
                        self._logger.error("    " + line)

    def get_last_dataset(self):
        select = src.queries.Select()

        select.set_table("status")
        select.set_cols("actual")
        select.set_filter("grace = ?", self._mode)
        select.build()

        cur = self._syscon.cursor()
        cur.execute(select.get_statement(), select.get_values())

        dataset = cur.fetchone()[0]

        cur.close()
        return dataset

    def set_last_dataset(self, value):
        now = datetime.today()

        upd = src.queries.Update("?")
        upd.set_table("status")
        upd.set_data(actual=value)
        upd.set_data(last_run=now.strftime("%Y-%m-%d %H:%M:%S"))
        upd.filter("grace = ?", self._mode)
        upd.build()

        cur = self._syscon.cursor()
        cur.execute(upd.get_statement(), upd.get_values())

        cur.close()

    def item_exist(self, item, attrs):
        query = src.queries.Select()
        query.set_table("attrs")
        query.set_cols("count(*)")
        query.set_filter("element = ?", item.decode("utf-8"))
        query.set_filter("element_mtime = ?", attrs["mtime"], src.queries.SQL_AND)
        query.set_filter("element_ctime = ?", attrs["ctime"], src.queries.SQL_AND)
        query.build()

        try:
            cur = self._oldcon.cursor()
            cur.execute(query.get_statement(), query.get_values())

            res = cur.fetchone()[0]

            cur.close()

            if res > 0:
                return True
            else:
                return False
        except Exception as ex:
            return False

    def add(self, item, attrs=None, acls=None):
        if attrs:
            self._add_element(item, attrs)

        if acls:
            for user in acls["user"]: 
                self._add_acl(item, user, "u")

            for group in acls["group"]:
                self._add_acl(item, group, "g")

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, value):
        self._mode = value

    @mode.deleter
    def mode(self):
        del self._mode

    @property
    def dataset(self):
        return self._dataset

    @dataset.setter
    def dataset(self, value):
        self._dataset = value

        if not self._mode:
            raise AttributeError, "Grace not definied"

    @dataset.deleter
    def dataset(self):
        del self._dataset

    @property
    def section(self):
        return self._section

    @section.setter
    def section(self, value):
        self._section = value

        if not self._dataset:
            raise AttributeError, "Dataset not definied"
        else:
            dbm = src.db.DBManager(self._cfg)
            self._con = dbm.open("/".join([self._cfg.get("general", "repository"),
                                 self._mode,
                                 str(self._dataset),
                                 self._section,
                                 ".store.db"]))

            old_dataset = self._dataset -1

            if old_dataset <= 0:
                old_dataset = self._cfg.getint("general", self.mode + "_grace")

            try:
                self._oldcon = dbm.open("/".join([self._cfg.get("general", "repository"),
                                 self._mode,
                                 str(old_dataset),
                                 self._section,
                                 ".store.db"]))
            except:
                self._oldcon = None

    @section.deleter
    def section(self):
        if self._con:
                self._con.commit()
                self._con.close()

        if self._oldcon:
            self._oldcon.rollback()
            self._oldcon.close()

        del self._section

class FsStorage(object):
    _cfg = None
    _repository = None

    _dataset = None
    _logger = None
    _mode = None
    _section = None

    def __init__(self, cfg):
        super(FsStorage, self).__init__()
        self._cfg = cfg
        self._repository = self._cfg.get("general", "repository")

        self._logger = logging.getLogger("Syncropy")

    def _dataset_path(self, previous):
        if previous:
            dataset = self._dataset - 1
        else:
            dataset = self._dataset

        if dataset == 0:
            dataset = self._cfg.getint("general", self._mode + "_grace")

        path = os.path.sep.join([self._repository, self._mode,
                        str(dataset), self._section])

        return path

    def check_dataset_exist(self):
        path = "/".join([self._repository, self._mode, str(self._dataset)])

        if os.path.exists(path):
            return True
        else:
            return False

    def remove_dataset(self):
        path = "/".join([self._repository, self._mode, str(self._dataset)])

        if os.path.exists(path):
            shutil.rmtree(path)

    def add(self, item, attrs, protocol):
        if attrs["type"] == "d":
            os.makedirs(self._dataset_path(False) + os.path.sep + item)
        elif attrs["type"] == "pl":
            os.link((self._dataset_path(True) + os.path.sep + item),
                    (self._dataset_path(False) + os.path.sep + item))
        elif attrs["type"] == "f":
            try:
                protocol.get_file(item, (self._dataset_path(False) + os.path.sep + item))
            except IOError as (errno, strerror):
                self._logger.error("I/O error({0}) for item {1}: {2}".format(errno, item, strerror))

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, value):
        self._mode = value

    @mode.deleter
    def mode(self):
        del self._mode

    @property
    def section(self):
        return self._section

    @section.setter
    def section(self, value):
        self._section = value

        if not os.path.exists("/".join([self._cfg.get("general", "repository"),
                                 self._mode,
                                 str(self._dataset),
                                 self._section])):
            os.makedirs("/".join([self._cfg.get("general", "repository"),
                                 self._mode,
                                 str(self._dataset),
                                 self._section]))

    @section.deleter
    def section(self):
        del self._section

    @property
    def dataset(self):
        return self._dataset

    @dataset.setter
    def dataset(self, value):
        self._dataset = value

        if not self._mode:
            raise AttributeError, "Grace not definied"

    @dataset.deleter
    def dataset(self):
        del self._dataset

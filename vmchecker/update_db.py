#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Updates marks for modified results"""

from __future__ import with_statement

import os
import time


from . import paths
from . import repo_walker
from . import submissions
from . import penalty
from . import vmlogging
from .paths import VmcheckerPaths
from .config import CourseConfig
from .coursedb import opening_course_db
from .courselist import CourseList

logger = vmlogging.create_module_logger('update_db')




class UpdateDb(object):
    def __init__(self, vmcfg):
        self.vmcfg = vmcfg
        self.vmpaths = VmcheckerPaths(vmcfg.root_path())
        self.walker = repo_walker.RepoWalker(vmcfg)



    def _get_grade_value(self, vmcfg, assignment, user, grade_path):
        """Returns the grade value after applying penalties and bonuses.

        Computes the time penalty for the user, obtains the other
        penalties and bonuses from the grade_path file
        and computes the final grade.

        The grade_path file can have any structure.
        The only rule is the following: any number that starts with '-'
        or '+' is taken into account when computing the grade.

        An example for the file:
            +0.1 very good comments
            -0.2  possible leak of memory on line 234 +0.1 treats exceptions
            -0.2 use of magic numbers
        """

        weights = [float(x) for x in
                    vmcfg.get('vmchecker', 'PenaltyWeights').split()]

        limit = vmcfg.get('vmchecker', 'PenaltyLimit')
        sss = submissions.Submissions(VmcheckerPaths(vmcfg.root_path()))
        upload_time = sss.get_upload_time_str(assignment, user)

        deadline = time.strptime(vmcfg.assignments().get(assignment, 'Deadline'),
                                 penalty.DATE_FORMAT)
        holidays = int(vmcfg.get('vmchecker', 'Holidays'))

        grade = 10
        words = 0
        word = ""

        with open(grade_path) as handler:
            for line in handler.readlines():
                for word in line.split():
                    words += 1
                    if word[0] in ['+', '-']:
                        try:
                            grade += float(word)
                        except ValueError:
                            pass

        #word can be either 'copiat' or 'ok'
        if words == 1:
            return word

        #at this point, grade is <= 0 if the homework didn't compile
        if grade <= 0:
            return 0

        if holidays != 0:
            holiday_start = vmcfg.get('vmchecker', 'HolidayStart').split(' , ')
            holiday_finish = vmcfg.get('vmchecker', 'HolidayFinish').split(' , ')
            penalty_value = penalty.compute_penalty(upload_time, deadline, 1 ,
                                weights, limit, holiday_start, holiday_finish)[0]
        else:
            penalty_value = penalty.compute_penalty(upload_time, deadline, 1 ,
                                weights, limit)[0]

        grade -= penalty_value
        return grade

    def _update_grades(self, vmcfg, force, assignment, user, grade_filename, course_db):
        """Updates grade for user's submission of assignment.

        Reads the grade's value only if the file containing the
        value was modified since the last update of the DB for this
        submission.

        """
        assignment_id = course_db.get_assignment_id(assignment)
        user_id = course_db.get_user_id(user)
        db_mtime = course_db.get_grade_mtime(assignment_id, user_id)

        mtime = os.path.getmtime(grade_filename)

        if force or db_mtime != mtime:
            # modified since last db save
            grade_value = self._get_grade_value(vmcfg, assignment, user, grade_filename)
            # updates information from DB
            course_db.save_grade(assignment_id, user_id, grade_value, mtime)

    def update_db(self, options, course_db):
        def _update_grades_wrapper(assignment, user, location, course_db, options):
            """A wrapper over _update_grades to use with repo_walker"""
            sbroot = self.vmpaths.dir_submission_root(assignment, user)
            grade_filename = paths.submission_results_grade(sbroot)
            if os.path.exists(grade_filename):
                self._update_grades(self.vmcfg, options.force, assignment, user, grade_filename, course_db)
                logger.info('Updated %s, %s (%s)', assignment, user, location)
            else:
                logger.error('No results found for %s, %s (check %s)',
                             assignment, user, grade_filename)

        # call the base implemnetation in RepoWalker.
        self.walker.walk(options, _update_grades_wrapper, args=(course_db, options))




def update_all(course_id):
    """Walk all submissions"""
    class stupid_hack_class:
        """We only need this because repo_walker takes an object
        from cmdline directly. Repo_walker must be refactored."""
        def __init__(self, course_id):
            """Repo_walker needs a field named 'all' set to True
            in the object to be able to walk all assignments"""
            self.all = True
            self.recursive = False
            self.user = None
            self.assignment = None
            self.ignore_errors = False
            self.course_id = course_id
            self.simulate = False
            self.force = False


    vmcfg = CourseConfig(CourseList().course_config(course_id))
    vmpaths = paths.VmcheckerPaths(vmcfg.root_path())

    # open Db
    with opening_course_db(vmpaths.db_file(), isolation_level="EXCLUSIVE") as course_db:
        # actual work: update according to options the db
        options = stupid_hack_class(course_id)
        u = UpdateDb(vmcfg)
        u.update_db(options, course_db)
